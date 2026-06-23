"""Application settings, loaded from the environment (prefix ``ABOS_``)."""

from __future__ import annotations

import urllib.parse as _url
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def normalize_db_url(url: str) -> str:
    """Coerce a managed-provider Postgres URL into an asyncpg SQLAlchemy URL.

    Managed Postgres (Neon/Render/Supabase/RDS) hands out ``postgres://`` or
    ``postgresql://`` URLs, often with ``?sslmode=require`` and
    ``?channel_binding`` — both libpq-only params the asyncpg driver rejects.
    This rewrites the scheme to ``postgresql+asyncpg://``, drops
    ``channel_binding``, and maps ``sslmode`` to asyncpg's ``ssl`` so TLS is
    preserved. URLs that already specify a ``+driver`` are left untouched.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix) :]
            break

    parts = _url.urlsplit(url)
    if not parts.query:
        return url
    kept: list[tuple[str, str]] = []
    sslmode: str | None = None
    for key, value in _url.parse_qsl(parts.query, keep_blank_values=True):
        if key == "sslmode":
            sslmode = value
        elif key == "channel_binding":
            continue
        else:
            kept.append((key, value))
    if sslmode and sslmode != "disable" and not any(k == "ssl" for k, _ in kept):
        kept.append(("ssl", "prefer" if sslmode in ("prefer", "allow") else "require"))
    return _url.urlunsplit(parts._replace(query=_url.urlencode(kept)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ABOS_", env_file=".env", extra="ignore")

    # Infra
    database_url: str = "postgresql+asyncpg://abos:abos@localhost:5432/abos"
    redis_url: str = "redis://localhost:6379/0"

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        return normalize_db_url(v)

    # Auth
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7

    # Envelope encryption: 32-byte master key, base64url-encoded.
    master_key: str = ""

    # Deployment topology. When true, the API process also runs the arq worker
    # in-process (think→act loop + cron jobs) instead of relying on a separate
    # worker service. Lets the whole app run on a single free-tier web instance;
    # leave false in production, where API and worker scale independently.
    run_worker_in_process: bool = False

    # TEMP (dev only): enables the dev toolkit (auto-login default account +
    # "delete all other accounts") used during active development. MUST be set to
    # false (or this whole feature removed) before going live. Kill-switch:
    # set ABOS_DEV_TOOLS_ENABLED=false.
    dev_tools_enabled: bool = True
    dev_default_email: str = "dev@abos.local"  # TEMP: the auto-login default account

    # Runtime safety caps (circuit breakers)
    max_task_depth: int = 4
    max_tasks_per_run: int = 200
    max_tasks_per_agent_window: int = 30
    max_loop_signature_repeats: int = 3
    max_steps_per_task: int = 12
    # Checkpoint a task's in-flight conversation to ``Task.transcript`` after each
    # step so it resumes after a restart. The checkpoint is cleared when the task
    # finishes, so the table holds only live tasks' working memory.
    persist_task_transcript: bool = True

    # Context compaction: a long autonomous task accumulates many turns, which
    # both inflates the per-step token cost and eventually overruns the model's
    # context window. When the in-loop conversation grows past
    # ``compaction_trigger_messages`` turns, the older turns are summarized into a
    # single compact recap (keeping the most recent ``compaction_keep_recent``
    # turns verbatim) so the loop can keep going cheaply. Disable to keep the full
    # raw history every step.
    context_compaction_enabled: bool = True
    compaction_trigger_messages: int = 24
    compaction_keep_recent_messages: int = 8

    # MCP (Model Context Protocol): founders can connect their own tool servers
    # (their CRM, analytics, internal APIs) so agents gain real tools without any
    # ABOS code change. MCP tools are screened by governance and never faked: a
    # server that is unreachable surfaces an honest error rather than a stub.
    mcp_enabled: bool = True
    mcp_timeout_seconds: float = 20.0
    mcp_max_tools_per_server: int = 40

    # Model defaults per role tier (overridable per-agent via Agent.model_pref)
    model_cheap: str = Field(default="claude-haiku-4-5")
    model_planner: str = Field(default="claude-sonnet-4-6")
    model_strategic: str = Field(default="claude-opus-4-8")

    # External integrations
    domain_registrar: str = "simulated"  # simulated | rdap | namecheap
    rdap_timeout_seconds: float = 4.0
    # Namecheap (only used when domain_registrar == "namecheap")
    namecheap_sandbox: bool = True
    namecheap_api_user: str = ""
    namecheap_api_key: str = ""
    namecheap_username: str = ""
    namecheap_client_ip: str = ""
    # Registrant contact as JSON, e.g. ABOS_NAMECHEAP_CONTACT='{"FirstName":...}'
    namecheap_contact: dict = Field(default_factory=dict)
    # Site hosting + DNS (landing pages and connecting bought domains) are
    # bring-your-own-key: credentials are per-company (Cloudflare) configured in
    # Settings, never global env vars. With no saved key the capability resolves to
    # None and reports unsupported (never faked).

    # Budget OS / Copilot
    runway_alert_days: float = 14.0  # raise a decision request below this runway
    roi_pause_floor: float = 0.05  # reputation.roi below this is "low ROI"
    digest_hour_utc: int = 13  # daily digest cron hour
    runway_recompute_minute: int = 0  # hourly runway recompute

    # Closed-loop runtime
    memory_recall_limit: int = 6  # prior learnings injected into an agent's context
    metrics_recall_limit: int = 8  # recent outcome signals injected into context

    # Company Memory — embeddings + recall ranking.
    # The embedder turns memory text into the vector used for similarity recall.
    # "local" (default) is a real neural model run in-process via fastembed
    # (ONNX/CPU) — no per-call cost and no network once the model is cached; it
    # degrades to the hashing embedder if fastembed/the model can't load.
    # "hashing" is the dependency-free lexical embedder (no model, fully offline).
    # "openai" is a real semantic model via the OpenAI embeddings REST API
    # (credential-gated by ABOS_OPENAI_API_KEY). All reduce to the 1536-dim pgvector
    # column. Switching providers re-embeds new writes only — backfill existing rows
    # if you change it on a populated DB.
    embeddings_provider: str = "local"  # local | hashing | openai
    embeddings_model: str = "text-embedding-3-small"  # openai model
    # Local fastembed model (small + CPU-friendly; 384-dim, zero-padded to 1536).
    local_embeddings_model: str = "BAAI/bge-small-en-v1.5"
    # Where fastembed caches the model. Set (and pre-warmed) in the Docker image so
    # the model is baked in at build time and never fetched over the network at
    # runtime; empty uses fastembed's default cache (fine for local dev).
    local_embeddings_cache_dir: str = ""
    embeddings_timeout_seconds: float = 10.0
    openai_api_key: str = ""  # platform key for the OpenAI embeddings endpoint
    # Recall blends similarity with recency so stale memories rank lower: a memory's
    # weight halves every ``half_life_days``. Candidates are pulled by pure
    # similarity (a pool of ``recall_limit * multiplier``, capped) then re-ranked.
    memory_recency_half_life_days: float = 30.0
    memory_candidate_multiplier: int = 4
    memory_candidate_cap: int = 60

    # Reputation-driven model selection: bump a struggling agent to a stronger
    # tier when its trust falls below the threshold.
    reputation_model_escalation: bool = True
    reputation_escalate_below: float = 0.4

    # Continuous operation: a recurring "business cycle" re-wakes the org.
    business_cycle_enabled: bool = True
    business_cycle_hour_utc: int = 12
    # Keep the org working without waiting for the daily cron: when a run finishes
    # (every task terminal, nothing awaiting the founder), automatically start the
    # next cycle after a short delay — as long as the company is active and has
    # budget headroom left. This is what makes the agents loop continuously.
    business_cycle_continuous: bool = True
    business_cycle_interval_seconds: int = 120  # delay between auto-continued cycles
    business_cycle_min_budget_cents: int = 50  # pause auto-continuation below this

    # Start lean: at launch the platform allocates only part of the monthly budget
    # across the starting fleet and leaves the rest as an unallocated pool the CEO
    # can deploy later (with the founder's approval) by hiring agents. Keeps the
    # team from committing the entire budget up front.
    launch_budget_reserve_fraction: float = 0.7

    # CEO audit loop: a delegated agent's result lands in ``auditing`` and the CEO
    # reviews it before it counts as ``done`` — approving it (forward) or reopening
    # it with comments (backward). This caps how many times the CEO may reopen the
    # same task before it is auto-accepted, so an audit↔redo loop can't run forever.
    max_audit_rounds: int = 2

    # Failure-retry loop: when a delegated task fails unexpectedly, it lands in
    # ``auditing`` and the CEO is woken to decide whether the failure looks
    # transient (worth re-running) or persistent (abandon it). This caps how many
    # times the CEO may re-run the same failed task before it stays failed, so a
    # fail↔retry loop can't burn budget forever.
    max_task_retries: int = 3

    # Restart safety: the durable business state lives in Postgres, but the work
    # queue is arq-on-Redis and ephemeral on this deployment. On worker startup,
    # rebuild the Redis queue from the DB (requeue orphaned/queued tasks and
    # re-arm idle companies). Disable to skip recovery on boot.
    recover_on_startup: bool = True

    # Web search seam (agents' window on the world); "simulated" is offline.
    web_search_provider: str = "simulated"  # simulated | tavily
    web_search_max_results: int = 5
    web_search_timeout_seconds: float = 10.0
    # Cost (cents) per Tavily *API credit*, metered through the CostMeter like any
    # other paid action. Tavily bills in credits (basic=1, advanced=2) and reports
    # the credits each call consumed, but never a dollar figure — so this is the
    # local credit→cents conversion. The meter reserves the estimated credits up
    # front and commits ``reported_credits × web_search_cost_cents`` as the actual
    # spend. The simulated provider is free (never charged).
    web_search_cost_cents: int = 2
    # Tavily (only used when web_search_provider == "tavily")
    tavily_api_key: str = ""
    tavily_search_depth: str = "basic"  # basic | advanced

    # Email seam (agents send sales/marketing/ops mail); "simulated" is offline.
    email_provider: str = "simulated"  # simulated | smtp | resend
    email_from: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    # Resend (only used when email_provider == "resend"): a developer-first email
    # API with a generous free tier (3,000/mo, 100/day) and custom-domain support.
    resend_api_key: str = ""

    # File store seam (the company's external file provider — Google Drive today).
    # Credentials are per-company, bring-your-own (connected in Settings), never a
    # global env var; with none saved the file capability resolves to None and the
    # tools report it's unsupported (never faked). This only names the top-level
    # folder created in the founder's Drive: ``.abos/<company>/<category>/…``.
    gdrive_root_folder: str = ".abos"

    # Issue-tracker seam (the Platform agent files bug/feature issues here);
    # "simulated" is offline and deterministic.
    issue_tracker: str = "simulated"  # simulated | github
    github_token: str = ""
    github_repo: str = "itamarsher/just-launch-it"

    # Investor review (onboarding): three agentic investors critique the venture.
    investor_review_enabled: bool = True
    investor_model: str = ""  # empty -> provider's planner-tier default

    # Public URL of THIS API as seen from the open internet (no trailing slash),
    # e.g. https://abos-api.onrender.com. Landing pages are static and hosted on a
    # third-party origin (Cloudflare Pages, *.pages.dev), so their built-in
    # email/waitlist capture form must POST to an absolute URL back here. Defaults
    # to the hosted API; override per environment. When empty, native on-page lead
    # capture is disabled (the page still publishes; the growth agent is told to
    # link to a hosted form instead).
    public_api_base_url: str = "https://abos-api.onrender.com"

    # Google Drive one-click connect (OAuth authorization-code flow). The
    # deployment registers ONE Google Cloud OAuth client (Drive scope) and sets
    # these; founders then connect their own Drive with a single button — no
    # per-company Cloud Console setup. The redirect URI to register on the client
    # is "<public_api_base_url>/integrations/google-drive/callback". When either is
    # unset the Connect button is hidden and Drive cannot be connected (the file
    # tools report the capability unsupported, exactly as before).
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    # Where to send the founder's browser once the OAuth callback finishes — the
    # web app, so we can land them back on the company's Settings page. Defaults to
    # the hosted web app; override per environment (no trailing slash).
    web_base_url: str = "https://abos-web.onrender.com"

    # CORS: browser origins allowed to call the API. Comma-separated in the
    # environment, e.g.
    #   ABOS_CORS_ALLOW_ORIGINS=https://abos-web.onrender.com,http://localhost:3000
    # The default "*" allows any origin. Per the CORS spec a wildcard origin
    # cannot be combined with credentials, so credentials are only enabled when
    # an explicit allowlist is configured (the frontend authenticates with a
    # bearer token, not cookies, so this costs nothing).
    # NoDecode keeps pydantic-settings from JSON-decoding the env value, so the
    # validator below can accept a plain comma-separated string.
    cors_allow_origins: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v):
        # Accept a comma-separated string from the environment.
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # Observability / rate limiting (productionization)
    log_level: str = "INFO"
    log_json: bool = True
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 120
    rate_limit_backend: str = "memory"  # memory | redis


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
