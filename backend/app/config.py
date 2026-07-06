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

    # Connection-pool sizing. Each pooled asyncpg connection holds a socket plus
    # per-connection buffers, so on a memory-constrained host (e.g. the 512MB
    # free tier, where the API and the in-process worker share this one engine)
    # the default 5+10 pool is worth trimming. ``pool_recycle`` also drops idle
    # connections so their buffers aren't pinned for the life of the process.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

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
    # Per-step output-token ceiling for the agent loop's LLM call. The effective
    # cap is ``min(this, provider.max_output_tokens(model))`` so it never exceeds
    # what the model accepts while still leaving room for a large deliverable
    # (e.g. a multi-item brief packed into one ``report_result`` summary). Kept
    # bounded because ``CostMeter`` reserves this as the worst-case output spend
    # up front, per step. Raise it for longer single-shot outputs.
    max_response_tokens: int = 8192
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

    # How much of a result to keep when surfacing it, so a large deliverable
    # isn't squeezed down to a sentence. ``max_result_summary_chars`` bounds a
    # summary captured from a plain-text finish (no ``report_result`` call) —
    # already limited by ``max_response_tokens``, this is just a defensive cap.
    # The ``collect_results_*`` pair bounds what a synthesizing agent sees when
    # it gathers finished sub-tasks: generous per child, with a total ceiling so
    # a fan-out of large briefs can't overrun the synthesizer's context window.
    max_result_summary_chars: int = 32_000
    collect_results_summary_chars: int = 4_000
    collect_results_total_chars: int = 24_000
    # Web-search results returned to an agent are clipped to this (with an explicit
    # truncation notice) — generous, since the loop now handles large context, but
    # bounded so a verbose provider can't flood one observation. 0 disables.
    web_search_max_chars: int = 8_000
    # Upper bound on the text handed to the embedding model. Company Memory stores
    # content in full (an unbounded ``Text`` column); only the *embedded* slice is
    # capped here, because real embedding APIs reject input past a fixed token
    # limit and would otherwise drop the vector entirely. ~24k chars ≈ 6k tokens,
    # safely under OpenAI's 8,191-token ceiling. 0 disables the cap.
    embeddings_max_input_chars: int = 24_000

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
    domain_registrar: str = "simulated"  # simulated | rdap | namecheap | card_checkout
    rdap_timeout_seconds: float = 4.0
    # Namecheap (only used when domain_registrar == "namecheap").
    # Live by default — set true to point at the Namecheap sandbox instead.
    namecheap_sandbox: bool = False
    namecheap_api_user: str = ""
    namecheap_api_key: str = ""
    namecheap_username: str = ""
    namecheap_client_ip: str = ""
    # Registrant contact as JSON, e.g. ABOS_NAMECHEAP_CONTACT='{"FirstName":...}'
    namecheap_contact: dict = Field(default_factory=dict)
    # Fail a domain registration *before* the irreversible call when the Namecheap
    # account balance can't cover it (clear "top up" error instead of a vendor 500).
    namecheap_precheck_balance: bool = True

    # Payment wallet — an agent's scoped access to real external spend.
    payment_wallet: str = "none"  # none | stripe_link
    stripe_secret_key: str = ""  # test or live key; used as-is (live moves real money)
    stripe_api_version: str = "2026-04-22.preview"  # SPT preview API
    stripe_timeout_seconds: float = 20.0
    stripe_currency: str = "usd"
    # Stripe Link agent wallet (only used when payment_wallet == "stripe_link")
    stripe_link_network_business_profile: str = ""  # seller profile the SPT is scoped to
    stripe_link_payment_method: str = ""  # wallet-backed PaymentMethod id (link-cli)
    stripe_link_return_url: str = ""
    stripe_link_token_ttl_seconds: int = 600  # SPT validity window
    # Card-checkout registrar (only used when domain_registrar == "card_checkout")
    card_checkout_merchant_name: str = "ABOS Domains"
    card_checkout_merchant_url: str = ""

    # Stripe Issuing — a budget-controlled virtual card the fleet uses to fund
    # external accounts (e.g. top up the Namecheap balance the registrar draws).
    # Authorizations are gated programmatically by the real-time-auth webhook.
    stripe_issuing_cardholder: str = ""  # existing cardholder id (ich_…)
    stripe_issuing_monthly_limit_cents: int = 50_000  # default hard cap per card
    stripe_webhook_secret: str = ""  # whsec_… — verifies the Issuing auth webhook
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
    embeddings_provider: str = "local"  # local | hashing | openai | remote
    embeddings_model: str = "text-embedding-3-small"  # openai model
    # Local fastembed model (small + CPU-friendly; 384-dim, zero-padded to 1536).
    local_embeddings_model: str = "BAAI/bge-small-en-v1.5"
    # Where fastembed caches the model. Set (and pre-warmed) in the Docker image so
    # the model is baked in at build time and never fetched over the network at
    # runtime; empty uses fastembed's default cache (fine for local dev).
    local_embeddings_cache_dir: str = ""
    embeddings_timeout_seconds: float = 10.0
    openai_api_key: str = ""  # platform key for the OpenAI embeddings endpoint
    # "remote" embedder: offload the local fastembed/ONNX model to a separate
    # service (``app.embed_service``) so the model's ~150-200MB lives in its own
    # memory budget, not the API's — the way to keep real semantic recall on the
    # 512MB free tier without paying for a bigger API instance. ``embeddings_url``
    # is that service's base URL (scheme optional; https assumed). The shared
    # secret authenticates the call (both services get the same value). With the
    # URL unset the provider yields no vector and recall falls back to recency.
    embeddings_url: str = ""
    embeddings_remote_secret: str = ""
    # Recall blends similarity with recency so stale memories rank lower: a memory's
    # weight halves every ``half_life_days``. Candidates are pulled by pure
    # similarity (a pool of ``recall_limit * multiplier``, capped) then re-ranked.
    memory_recency_half_life_days: float = 30.0
    memory_candidate_multiplier: int = 4
    memory_candidate_cap: int = 60
    # Heal memories written with no vector (e.g. while a ``remote`` embedding
    # service was cold-starting): a periodic job re-embeds ``embedding IS NULL``
    # rows once the embedder is warm. Bounded per company per run so the pass stays
    # light on a small instance; the cron also keeps a remote embedder warm.
    embedding_backfill_enabled: bool = True
    embedding_backfill_batch: int = 50

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
    # End-of-cycle retrospective: before a business cycle closes, the CEO runs a
    # retrospective stage — every agent that did work this cycle reflects (what went
    # right/wrong, impactful improvement suggestions) and the CEO ingests it, deciding
    # what to implement now vs. route to the Platform agent as a capability request.
    business_cycle_retrospective_enabled: bool = True

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

    # Self-validation critic: an INDEPENDENT reviewer (a separate metered LLM call
    # with no access to the producing agent's reasoning) that plays devil's advocate
    # on an agent's work and, for visual outputs (landing pages, generated images),
    # opinionates on the actual material — literally seeing generated images via a
    # vision model. Its feedback is fed back to the agent, which iterates until the
    # critic is satisfied or a round cap is hit. Fail-open: if the critic can't run
    # (no key, error) the work proceeds unblocked.
    critic_enabled: bool = True
    # Model for the critic. Empty → the provider's planner-tier default (a capable,
    # vision-capable model on every provider). Overridable per deployment.
    critic_model: str = ""
    # How many revision rounds a VISUAL output (page/image) may be pushed back
    # before it's accepted as-is, so an agent↔critic loop on one artifact ends.
    visual_critic_max_rounds: int = 2
    # How many times the devil's-advocate critic may send a task back for a rewrite
    # before its result is accepted, so a critique↔redo loop can't run forever.
    critic_max_rounds: int = 1

    # Chat collaboration loop: agents discuss shared topics in mutual channels,
    # which keeps collaboration distributed instead of routing everything through
    # the CEO. To stop two agents from ping-ponging replies forever, a channel is
    # allowed this many messages before the next post escalates to the CEO, who
    # decides whether the discussion continues and grants the next allowance (see
    # ``app.runtime.tools.chat``). The CEO is exempt — they are the overseer, never
    # throttled — and founder DMs (where a human paces the thread) are never capped.
    chat_message_budget: int = 10

    # Failure-retry loop: when a delegated task fails unexpectedly, it lands in
    # ``auditing`` and the CEO is woken to decide whether the failure looks
    # transient (worth re-running) or persistent (abandon it). This caps how many
    # times the CEO may re-run the same failed task before it stays failed, so a
    # fail↔retry loop can't burn budget forever.
    max_task_retries: int = 3

    # Max tasks the arq worker runs concurrently. Each in-flight task holds an
    # agent loop's working set (system prompt, tool specs, the growing message
    # history, the latest LLM response), so on the free tier — where the worker
    # runs inside the API process under a 512MB cap — this is the main lever on
    # peak concurrent memory. Lower it there; keep it higher on the dedicated
    # worker service.
    worker_max_jobs: int = 10

    # Defensive cap on how many bytes an agent's ``read_company_file`` will pull
    # into memory. A file is materialized whole to decode it as text, so without
    # a bound a runaway agent reading a large attachment could OOM the box. 0
    # disables the guard.
    max_file_read_bytes: int = 5_000_000

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

    # Brand media-generation seam (the design agent's image/video synthesis);
    # "simulated" is offline (NOT connected — generate_image/generate_video report
    # the capability is unsupported). "google" wires Nano Banana (Gemini image) +
    # Veo (video) via the Generative Language API.
    media_gen_provider: str = "simulated"  # simulated | google
    # Google Generative Language API key (only used when media_gen_provider=google).
    # A per-company BYO key, stored under the "nano_banana" provider slot, overrides
    # this global default at resolution time.
    google_api_key: str = ""
    nano_banana_image_model: str = "gemini-2.5-flash-image"
    nano_banana_video_model: str = "veo-3.0-generate-001"
    media_gen_timeout_seconds: float = 60.0
    # Veo generation is a long-running operation; poll it on this cadence up to the
    # max wait before giving up.
    media_gen_video_poll_seconds: float = 8.0
    media_gen_video_max_wait_seconds: float = 240.0
    # Per-asset cost (cents) reserved+committed through the CostMeter, like any other
    # paid action. Images are cheap; a short video clip is materially pricier.
    media_image_cost_cents: int = 4
    media_video_cost_cents: int = 50

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
    # folder created in the founder's Drive: ``.galaxia/<company>/<category>/…``.
    gdrive_root_folder: str = ".galaxia"

    # Issue-tracker seam (the Platform agent files bug/feature issues here).
    # Defaults to real GitHub issues, authenticated with a centralized global
    # ``ABOS_GITHUB_TOKEN`` set in the deployment env (Render). Set
    # ``ABOS_ISSUE_TRACKER=none`` to force the tracker off.
    issue_tracker: str = "github"  # github | none | simulated
    github_token: str = ""
    github_repo: str = "itamarsher/just-launch-it"

    # ── Galaxia: the dogfooding company (ABOS running on itself) ──────────────
    # Galaxia is the reference business ABOS operates on its own product: its
    # agents' unmet needs (report_bug / request_capability) accrue in the shared
    # feature-request backlog, and Galaxia's Platform agent is the ONLY actor
    # authorized to promote that backlog into real tracker issues on this repo
    # (see runtime/tools/platform.py). Promotion authority is keyed to the
    # founder-user's membership, so that company must actually exist in every
    # deployment or the whole demand→issue loop is dead. It is therefore
    # bootstrapped deterministically and idempotently at API startup
    # (app.services.galaxia). Keep ``galaxia_founder_user_id`` stable — it is the
    # promoter gate.
    galaxia_bootstrap_enabled: bool = True
    galaxia_founder_user_id: str = "91da8f48-d302-4921-bb4a-c3f2c18eaf3d"
    galaxia_founder_email: str = "founder@galaxia.abos"
    # Fixed company id makes the bootstrap idempotent. Empty → derived
    # deterministically from the founder id (uuid5), so there is never a magic
    # literal to keep in sync across environments.
    galaxia_company_id: str = ""
    galaxia_company_name: str = "GalaxiaOS"
    # Galaxia's monthly operating budget (cents). Modest by default — its work is
    # platform triage, metered through the same CostMeter as any company.
    galaxia_monthly_budget_cents: int = 50_000
    # The mission fed to the generator (mission → summary/objectives/KRs → fleet).
    # Overridable via ABOS_GALAXIA_MISSION, but note the bootstrap reconciles the
    # stored mission to this on the next boot (see app.services.galaxia), so config
    # is the source of truth even for an already-provisioned Galaxia.
    galaxia_mission: str = (
        "Make owning an autonomous business a right, not a privilege. GalaxiaOS is a "
        "free, open-source operating system that lets any person on the planet stand "
        "up and run a real company operated by a fleet of AI agents — a CEO and the "
        "functions a business actually needs (growth, research, product, finance, "
        "governance, and more) — under a hard budget and a governance layer, with the "
        "founder acting as a board member rather than an operator. Founders bring "
        "their own model key (BYOK): owning or creating an autonomous business must "
        "never depend on a subscription or a gatekeeper.\n\n"
        "Our business is to build and operate GalaxiaOS itself — we dogfood our own "
        "product. GalaxiaOS runs as a company on GalaxiaOS: the same agent fleet "
        "every founder gets operates our own roadmap, growth, research, finance, and "
        "governance. When any agent — ours, or any other company's on the platform — "
        "hits a limitation, that unmet need becomes a demand signal, and the "
        "highest-demand needs are turned into shipped product improvements "
        "automatically: need → tracker issue → implementation → reviewed, merged, and "
        "deployed, with no human in the loop except the decisions a founder must own "
        "(security, money, data access, and irreversible calls). Every founder's "
        "friction makes the product better for every founder, and the platform's "
        "capabilities compound as its users' real needs ship continuously.\n\n"
        "We serve aspiring and solo founders, indie hackers, and small teams "
        "worldwide who have ideas and intent but not the capital, headcount, or "
        "technical depth to operate a company — especially the people a paid "
        "gatekeeper would exclude. We win when a non-technical person, anywhere, can "
        "describe a mission and a budget and have a functioning, self-improving "
        "business running the same day.\n\n"
        "We sustain the open core without ever paywalling the core capability: "
        "optional hosted/managed convenience, a future agent-and-capability "
        "marketplace, and support/partnerships. The core stays free, open-source, and "
        "BYOK so adoption is unconstrained."
    )
    # Standing constraints attached to Galaxia's mission (the founder's guardrails).
    galaxia_constraints: list[str] = [
        "Core product stays free, open-source, and BYOK — never paywall the core capability.",
        "Reserve budget before spending; never exceed the budget.",
        "Escalate security, money-movement, data-access, and irreversible changes to the founder.",
        "Act only through real tools; never fabricate or assume an unverified result.",
        "Prefer reusing the existing fleet over growing headcount.",
    ]

    # Scheduled promoter: a cron drains the shared feature-request backlog into
    # real tracker issues on Galaxia's behalf, so accrued demand becomes issues
    # without waiting for a human to prompt the Platform agent. Only entries with
    # at least ``min_votes`` are promoted, ``batch`` at a time per tick (the tracker
    # dedupes, so re-promotion is a +1, not a duplicate).
    galaxia_promote_enabled: bool = True
    galaxia_promote_min_votes: int = 1
    galaxia_promote_batch: int = 5
    galaxia_promote_minute: int = 7  # once/hour at :07

    # Loop-closing reconciler: a cron checks each promoted backlog entry's tracker
    # issue and, once it is closed (the fix merged), marks the entry ``delivered``
    # and notifies the companies that requested it — so agents learn the gap they
    # reported is now closed instead of re-requesting it forever.
    galaxia_reconcile_enabled: bool = True
    galaxia_reconcile_batch: int = 25
    galaxia_reconcile_minute: int = 37  # once/hour at :37 (offset from the promoter)

    # Which deployment this is. The CURRENT default deployment is the *dogfooding*
    # environment: GalaxiaOS runs here and is allowed to experiment, self-modify,
    # and deploy. Dev tooling (incl. the Galaxia reset endpoint) is enabled here.
    #
    # TODO(production-split): before onboarding the FIRST external users, stand up a
    # SEPARATE production environment (own Render services + database + secrets) with
    # environment="production", galaxia_bootstrap_enabled=false, and dev_tools_enabled
    # =false — so real customer businesses never share infra with GalaxiaOS's own
    # experimentation/self-deploy loop. See docs/DOGFOODING_OPERATIONS.md#environments.
    environment: str = "dogfooding"  # dogfooding | production

    # Re-provision Galaxia from fleet creation on the next boot, preserving saved
    # BYOK keys. A convenience for the heavily-developed phase: set it, redeploy
    # once, then UNSET it (it fires on every boot while true). Manual, safer path:
    # POST /dev/galaxia/reset.
    galaxia_reset_on_boot: bool = False

    # Render deployment observability (so agents can see what's happening with our
    # own deploys). A read-only Render API key; global because GalaxiaOS owns the
    # dogfooding Render account. A company may also connect its own via a BYOK
    # "render" key. Without either, the render_* tools report they're not connected.
    render_api_key: str = ""
    render_api_base_url: str = "https://api.render.com/v1"
    # Owner (team/user) id for the Render logs API — required by GET /v1/logs, which
    # the `get_render_logs` debug tool uses. Without it, log reads report they need
    # configuring (deploy-status tools still work with just the key).
    render_owner_id: str = ""

    # Reliability monitor: Galaxia watches its OWN failed agent tasks, wakes the
    # Platform agent to investigate each (reading the code, and the Render deploys
    # when it looks infrastructure-related), and files a bug report — which flows
    # through the promoter → tracker issue → Claude Code auto-fix pipeline. Scoped
    # to Galaxia and to its own failures. ``batch`` caps investigations per tick.
    galaxia_failure_monitor_enabled: bool = True
    galaxia_failure_monitor_batch: int = 5
    galaxia_failure_monitor_minute: int = 22  # once/hour (offset from :07 / :37)

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
