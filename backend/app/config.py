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


def normalize_base_url(url: str) -> str:
    """Coerce a configured public base URL into a clean absolute origin.

    The OAuth redirect URI is built as ``<base>/auth/google/callback`` and must
    match — byte for byte — the URI registered on the Google OAuth client. Two
    operator mistakes silently break that match:

    - a **missing scheme** (``abos-api.onrender.com``) — the common Render trap,
      since ``NEXT_PUBLIC_API_BASE_URL`` is auto-wired from the service *host*
      (no scheme), so the same host-only value gets pasted here; and
    - a **trailing slash** (``https://abos-api.onrender.com/``).

    Both would otherwise produce a redirect URI Google rejects with
    ``redirect_uri_mismatch``. Normalize to ``<scheme>://host[:port][/path]`` with
    no trailing slash. Scheme defaults to ``https`` (``http`` for local hosts, so
    dev keeps working). An empty value is left empty (feature stays disabled).
    """
    v = (url or "").strip().rstrip("/")
    if not v:
        return v
    if "://" not in v:
        host = v.split("/", 1)[0].split(":", 1)[0].lower()
        scheme = "http" if host in ("localhost", "127.0.0.1") else "https"
        v = f"{scheme}://{v}"
    return v


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

    # ── Managed mode (hosted "no keys needed" tier) ─────────────────────────
    # When true, a founder who stores NO provider key of their own still gets a
    # working fleet: the deployment supplies a shared platform LLM key (and the
    # platform-configured read-only capabilities — web search, media-gen), and
    # the resulting spend is metered against a per-founder free allowance that
    # can convert to paid managed usage. This is the seam that lets the hosted
    # product launch with zero keys. It is DEFAULT OFF so self-hosting stays
    # strictly BYOK (the operator would be paying for every tenant otherwise).
    # A founder's own stored key always wins over the platform key, is never
    # metered against the platform allowance, and lifts every managed limit.
    managed_mode_enabled: bool = False
    # The shared LLM the platform funds for managed companies. The provider is
    # explicit (unlike BYOK, where the stored key's slot picks the provider),
    # and must be one of providers.registry.supported_providers(). The key is a
    # deployment secret — never an ``ApiKey`` row, never returned by any API,
    # only ever handed to ``provider.complete``. Empty key => managed LLM is
    # unavailable even when managed_mode_enabled (companies without a BYOK key
    # can't launch), so set both when turning managed mode on.
    #
    # Defaults to ``openrouter`` (open-source models over an OpenAI-compatible
    # host): a subsidized free tier wants the cheapest capable tokens, and OSS
    # models on OpenRouter are typically far cheaper per token than Claude. Point
    # it at ``anthropic`` (or any supported provider) if you'd rather fund Claude.
    platform_llm_provider: str = "openrouter"
    platform_llm_api_key: str = ""
    # Per-founder lifetime free allowance of platform-funded spend (cents). Once
    # a founder's cumulative platform spend crosses this, managed capabilities
    # stop for them until they add their own key or upgrade to paid managed.
    # Pooled per founder ACCOUNT (across all their companies) so spinning up new
    # companies can't multiply the free tier.
    platform_free_tier_cents: int = 200
    # Abuse backstop: cap platform-funded spend per founder per UTC day, so a
    # single account can't burn the shared key in one burst even within its free
    # allowance. 0 disables the daily guard.
    platform_daily_cap_cents: int = 100
    # Stripe metered price id for the paid managed tier (usage-based billing of
    # platform-funded spend). Empty => the upgrade-to-managed flow reports it is
    # not configured (the free tier still works; over-cap companies are asked to
    # bring their own key). Reuses ABOS_STRIPE_SECRET_KEY for the API call.
    stripe_managed_price_id: str = ""
    # Markup applied to platform-funded cost when billing paid-managed usage
    # (1.0 = passthrough, 1.3 = +30%). This is the hosted-convenience margin.
    managed_billing_markup: float = 1.3

    # Deployment topology. When true, the API process also runs the arq worker
    # in-process (think→act loop + cron jobs) instead of relying on a separate
    # worker service. Lets the whole app run on a single free-tier web instance;
    # leave false in production, where API and worker scale independently.
    run_worker_in_process: bool = False
    # Free-tier keep-warm: when the worker runs in-process on a host that idles
    # web services out after inactivity (e.g. Render free), a periodic self-ping to
    # the public URL keeps inbound traffic flowing so the worker isn't spun down and
    # agent cycles keep running. Opt-in; a no-op without a public URL. Leave false on
    # an always-on instance (a separate worker service, or a paid plan).
    keep_warm_enabled: bool = False

    # Safety net for a task parked in ``waiting_approval`` with nothing that can
    # resume it (no pending decision and no pending chat-wait) — an orphan that both
    # blocks its objective and, because waiting_approval counts as "active", stops the
    # continuous business cycle from ever winding down (a silent company deadlock).
    # The reaper fails such a task once it has sat orphaned longer than this grace
    # window (long enough that a just-created decision/wait is never raced).
    orphaned_approval_grace_minutes: int = 15

    # Human-backed web search: when no automated web-search provider is connected,
    # route an agent's web_search/web_fetch to the FOUNDER (a DM the founder — or
    # their AI operator — answers with the findings) instead of reporting the
    # capability unsupported. Turns "the founder is our search agent" into a real
    # first-class fallback. Off reverts to unsupported_capability.
    web_search_founder_fallback: bool = True

    # Safety net for a task parked on a chat reply-wait that never gets an answer —
    # the founder is away, or a teammate agent crashed. The message-budget escalation
    # only catches a *chatty* loop; silence blocks the task (and, since waiting_approval
    # is active, the whole business cycle) indefinitely. After this window with no
    # reply, the reaper posts a "no reply — proceed or escalate" note, expires the
    # wait, and re-queues the task so it can finish instead of hanging forever.
    chat_reply_timeout_minutes: int = 30

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
    # All three default to ``DEFAULT_MAX_OBSERVATION_CHARS`` (~100k chars ≈ 28k
    # tokens): generous enough that real deliverables pass through whole, still
    # bounded so no single observation floods the loop.
    max_result_summary_chars: int = 100_000
    collect_results_summary_chars: int = 100_000
    collect_results_total_chars: int = 100_000
    # Web-search results returned to an agent are clipped to this (with an explicit
    # truncation notice) — generous, since the loop now handles large context, but
    # bounded so a verbose provider can't flood one observation. 0 disables.
    web_search_max_chars: int = 100_000
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

    # Self-hosted OpenAI-compatible LLM endpoint (vLLM/Ollama/TGI) for running
    # the fleet on open-source models. Hosted OSS aggregators (OpenRouter, Groq,
    # Together) need no config — they're BYOK with baked-in URLs. This is only
    # for pointing at your own server: set the base URL and the per-tier model
    # slugs it serves. Empty base URL => the "openai_compat" provider is not
    # offered (see providers/registry.py).
    openai_compat_base_url: str = ""
    openai_compat_model_cheap: str = ""
    openai_compat_model_planner: str = ""
    openai_compat_model_strategic: str = ""

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
    # Founder decision delegate (webhook notify + involvement-based routing). Global
    # kill switch for the per-minute triage cron; per-company notification config
    # (webhooks, Telegram link) lives in the DB, and routing itself is driven by each
    # member's involvement prose (see app.services.delegate / involvement_router).
    delegate_enabled: bool = True
    # Shared platform Telegram bot for founder notifications (@GalaxiaOSBot). The
    # token is a platform secret (one bot serves every founder); per-company we
    # only store the founder's linked chat id. Empty ⇒ Telegram delivery is off.
    telegram_bot_token: str = ""
    # Verifies inbound updates from Telegram (X-Telegram-Bot-Api-Secret-Token);
    # registered with the bot's webhook at startup. Empty ⇒ inbound is unverified
    # (fine for a throwaway/test bot, but set one in production).
    telegram_webhook_secret: str = ""

    # Closed-loop runtime
    memory_recall_limit: int = 6  # prior learnings injected into an agent's context
    metrics_recall_limit: int = 8  # recent outcome signals injected into context
    # How long a pull worker's claim on an initiative holds before it can be
    # reassigned (RFC 0001, step 3). Long enough for a human/scheduled worker to
    # act; a dead worker's claim expires and the initiative is offered again.
    initiative_lease_seconds: int = 900

    # Live mission log — an ephemeral, Redis-backed ring of the agents' latest
    # milestone updates, surfaced live on the game dashboard (never persisted).
    mission_log_max_entries: int = 10  # how many recent updates to retain / show
    mission_log_ttl_seconds: int = 6 * 3600  # key self-expiry (ephemeral by design)
    mission_log_headline_max_chars: int = 160
    mission_log_detail_max_chars: int = 400

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
    # team from committing the entire budget up front. (Was 0.7 — that left each
    # functional agent with only pennies on a small budget, so routine metered work
    # tripped BudgetExceeded constantly; 0.4 gives the working fleet a usable slice.)
    launch_budget_reserve_fraction: float = 0.4

    # A company can't function without a working file store — its agents file every
    # report, artifact, and saved document there, and a fleet that can't persist its
    # work is dead on arrival. So launching requires a connected storage provider
    # (Google Drive today), for AI-agent-driven onboarding (Founder MCP) just as for
    # a human founder. Enforced only where storage *can* be connected (the Drive
    # OAuth app is configured on the deployment); off deployments/tests skip it.
    require_storage_to_launch: bool = True

    # When the founder DECLINES an outbound message (e.g. a landing page), don't let
    # the fleet re-escalate the identical send from the next task/cycle for this many
    # minutes — the per-task rejection only stopped the same task, so without this a
    # declined page gets re-submitted (and re-rejected) in a loop. 0 disables.
    founder_rejection_cooldown_minutes: int = 180

    # Floor for a functional agent's per-agent budget slice, so a lean weighted
    # split never leaves an agent with too little to take a single metered step
    # (an LLM call + a web search or two). Drawn from the reserve pool; scaled back
    # only if the whole fleet's floors wouldn't fit the company budget.
    launch_agent_min_budget_cents: int = 100

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

    # arq hard-cancels any job still running past this many seconds (its default
    # is 300s). A single ``run_task`` job drives a full agent loop of sequential
    # LLM calls and tool invocations, which routinely exceeds 5 minutes for
    # non-trivial work — so the default left legitimate long-running tasks
    # cancelled mid-flight. Generous enough that only a genuinely stuck task
    # should ever hit it.
    worker_job_timeout_seconds: int = 1800

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
    # Web fetch (page extraction) rides the same Tavily provider/key as web_search.
    # How many URLs one web_fetch call may extract (Tavily bills ~1 credit per 5 URLs
    # at basic depth, 2 at advanced), and the char cap on the combined observation
    # handed back (page bodies are large; 0 disables the cap).
    web_fetch_max_urls: int = 5
    web_fetch_max_chars: int = 50_000
    # Tavily (only used when web_search_provider == "tavily")
    tavily_api_key: str = ""
    tavily_search_depth: str = "basic"  # basic | advanced
    tavily_extract_depth: str = "basic"  # basic | advanced (web_fetch)

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
    # Bounded retry-with-backoff for transient HTTP 429s on the initiating call
    # (generateContent / predictLongRunning). Honors a Retry-After header when Google
    # sends one, otherwise backs off exponentially from this base.
    media_gen_max_retries: int = 2
    media_gen_retry_backoff_seconds: float = 1.0
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
    # The ``owner/repo`` the platform files issues against. Set per deployment via
    # ``ABOS_GITHUB_REPO``; empty by default so no repository is assumed.
    github_repo: str = ""

    # ── Operator (dogfooding) company: GalaxiaOS running on itself ────────────
    # A deployment may name ONE ordinary company as the operator company (the
    # reference business ABOS dogfoods on). It's the only actor authorized to promote
    # the shared feature-request backlog into tracker issues (runtime/tools/platform.py)
    # and to use the deployment's global Render key (runtime/tools/render_ops.py), and
    # the operator crons below run on its behalf. This is EXPLICIT config pointing at a
    # normal, normally-onboarded, normally-funded company — not a magic flag. Empty =>
    # no operator company (crons no-op, global Render fallback off).
    platform_company_id: str = ""

    # Scheduled promoter: a cron drains the shared feature-request backlog into
    # real tracker issues on the platform company's behalf, so accrued demand
    # becomes issues without waiting for a human to prompt the Platform agent. Only
    # entries with at least ``min_votes`` are promoted, ``batch`` at a time per tick
    # (the tracker dedupes, so re-promotion is a +1, not a duplicate).
    platform_promote_enabled: bool = True
    platform_promote_min_votes: int = 1
    platform_promote_batch: int = 5
    platform_promote_minute: int = 7  # once/hour at :07

    # Loop-closing reconciler: a cron checks each promoted backlog entry's tracker
    # issue and, once it is closed (the fix merged), marks the entry ``delivered``
    # and notifies the companies that requested it — so agents learn the gap they
    # reported is now closed instead of re-requesting it forever.
    platform_reconcile_enabled: bool = True
    platform_reconcile_batch: int = 25
    platform_reconcile_minute: int = 37  # once/hour at :37 (offset from the promoter)

    # Skill optimizer (SkillOpt-style): a cron that learns which shared playbooks are
    # underperforming from real skill-usage outcomes, then proposes validation-gated,
    # bounded edits — filed as issues into the same triage→implement→CI→auto-merge
    # pipeline a capability request uses, so a validated skill edit reviews-and-merges
    # itself. Opt-in (defaults OFF) because it edits the skill library autonomously;
    # runs on the platform company only, and no-ops without an LLM + tracker.
    skill_optimize_enabled: bool = False
    skill_optimize_minute: int = 47  # once/hour at :47 (offset from the other crons)
    skill_optimize_batch: int = 3  # candidate skills examined per tick (budget cap)
    skill_optimize_window_days: int = 14  # outcome window the signal aggregates over
    skill_optimize_min_samples: int = 5  # don't rewrite off fewer than this many tasks
    skill_optimize_success_ceiling: float = 0.8  # only consider skills at/under this success rate
    skill_optimize_max_edits: int = 5  # learning-rate: max bounded changes per candidate
    skill_optimize_gate_min_margin: int = 1  # candidate must beat current by ≥ this to propose
    skill_optimize_gate_auto_margin: int = 3  # ≥ this gate margin → auto path; else flag for a human
    skill_optimize_model: str = ""  # empty → the provider's planner-tier default
    # Labels put on a high-confidence proposal so it enters the auto-merge pipeline.
    # NoDecode + the validator below accept a plain comma-separated env string.
    skill_optimize_labels: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["skill-optimize"]
    )

    @field_validator("skill_optimize_labels", mode="before")
    @classmethod
    def _split_skill_labels(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # Which deployment this is. The CURRENT default deployment is the *dogfooding*
    # environment: GalaxiaOS runs here and is allowed to experiment, self-modify,
    # and deploy.
    #
    # For a hardened production deployment, run a SEPARATE environment (its own
    # services + database + secrets) with environment="production", so customer
    # businesses never share infrastructure with a self-modifying/self-deploy loop.
    # See docs/DOGFOODING_OPERATIONS.md#environments.
    environment: str = "dogfooding"  # dogfooding | production

    # Render deployment observability (so agents can see what's happening with our
    # own deploys). A read-only Render API key; global because GalaxiaOS owns the
    # dogfooding Render account. Only the platform company may use it; any other
    # company must connect its own via a BYOK "render" key. Without either, the
    # render_* tools report they're not connected.
    render_api_key: str = ""
    render_api_base_url: str = "https://api.render.com/v1"
    # Owner (team/user) id for the Render logs API. Optional: when empty it is
    # resolved automatically from the API key (GET /v1/owners) and cached, so the
    # key alone is enough. Only set this to disambiguate a key that can see more
    # than one owner.
    render_owner_id: str = ""

    # Connected external runtime (RFC 0001): a managed OpenClaw Gateway that the
    # `external` backend delegates a function's execution to over OpenClaw's
    # OpenAI-compatible HTTP API. Empty base URL => no worker is bound and an
    # `external` agent fails with a clear "no runtime connected" message.
    openclaw_base_url: str = ""
    openclaw_api_key: str = ""
    # Model/agent route. Empty => route by tenant+function
    # ("openclaw/<company_id>:<function>"), so each business function maps to its own
    # per-tenant OpenClaw agent persona (RFC 0001 §6 — never a shared persona).
    openclaw_model: str = ""
    openclaw_timeout_seconds: float = 120.0

    # Default runtime binding for a newly *generated* functional agent (RFC 0001
    # §5 — the batteries-included, same-day binding). "native" runs the in-process
    # loop; "external" auto-binds each generated function to the managed OpenClaw
    # Gateway. "external" only takes effect when a Gateway is actually configured
    # (openclaw_base_url set), so a mis-set default can never strand agents with no
    # worker — see `services.worker_binding.default_backend_for`. The CEO always
    # runs natively regardless (it orchestrates the company).
    default_agent_backend: str = "native"

    # Secret that signs per-(company, function) connection tokens for the
    # Business-Function MCP endpoint (RFC 0001 pull transport). Empty => the
    # endpoint is disabled and all connection attempts are rejected, so the pull
    # transport is strictly opt-in. Rotating this invalidates every issued token.
    function_connection_secret: str = ""

    # Secret that signs per-user FOUNDER connection tokens for the Founder MCP
    # endpoint (/connect/founder) — the credential a user's own AI presents to
    # register, onboard, launch, and steer their companies (agent-first operation).
    # Empty => the Founder MCP is disabled and all connection attempts are rejected,
    # so it is strictly opt-in. Rotating this invalidates every issued founder token.
    founder_connection_secret: str = ""

    # Reliability monitor: the platform company watches its OWN failed agent tasks,
    # wakes the Platform agent to investigate each (reading the code, and the Render
    # deploys when it looks infrastructure-related), and files a bug report — which
    # flows through the promoter → tracker issue → Claude Code auto-fix pipeline.
    # Scoped to the platform company and to its own failures. ``batch`` caps
    # investigations per tick.
    platform_failure_monitor_enabled: bool = True
    platform_failure_monitor_batch: int = 5
    platform_failure_monitor_minute: int = 22  # once/hour (offset from :07 / :37)

    # ── System-wide error monitoring → auto-fix issues ────────────────────────
    # Captures errors from two sources and escalates each to a deduplicated
    # tracker issue that the Claude Code auto-fix pipeline can pick up:
    #   1. Code errors — any exception logged with a traceback anywhere in the API
    #      or worker (the request 500 handler, cron jobs, the worker loop) is
    #      forwarded by a logging handler (app.observability) to error_monitor.
    #   2. Render platform errors — a cron scans our own Render services/deploys
    #      (via the read-only Render API) for failed deploys and suspended
    #      services and files an issue.
    # Off by default (needs a tracker + a real deployment); flip on in the hosted
    # env. Issues are filed with ``error_monitor_labels`` so they route to the
    # right automation — the default routes through issue-triage, which adds
    # ``claude-implement``; set it to ``claude-implement`` to auto-fix directly.
    error_monitor_enabled: bool = False
    error_monitor_labels: str = "bug,auto-detected"  # comma-separated tracker labels
    # Don't refile the same fingerprint within this window (in-process dedup, on
    # top of the tracker's own title-based dedup+"+1" demand counting).
    error_monitor_cooldown_minutes: int = 60
    # Max distinct error fingerprints to remember for the cooldown window.
    error_monitor_cache_size: int = 512
    # Render platform scan cron (once/hour at :52, offset from the others). Gated
    # by error_monitor_enabled AND a Render API key being set.
    render_monitor_enabled: bool = True
    render_monitor_minute: int = 52
    render_monitor_deploy_lookback: int = 5  # deploys inspected per service

    # Investor review (onboarding): three agentic investors critique the venture.
    investor_review_enabled: bool = True
    investor_model: str = ""  # empty -> provider's planner-tier default

    # Public URL of THIS API as seen from the open internet (no trailing slash),
    # e.g. https://abos-api.onrender.com. Landing pages are static and hosted on a
    # third-party origin (Cloudflare Pages, *.pages.dev), so their built-in
    # email/waitlist capture form must POST to an absolute URL back here. Set per
    # environment via ``ABOS_PUBLIC_API_BASE_URL``. When empty (the default),
    # native on-page lead capture is disabled (the page still publishes; the
    # growth agent is told to link to a hosted form instead).
    public_api_base_url: str = ""

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
    # web app, so we can land them back on the company's Settings page. Set per
    # environment via ``ABOS_WEB_BASE_URL`` (no trailing slash).
    web_base_url: str = ""

    @field_validator("default_agent_backend")
    @classmethod
    def _valid_default_backend(cls, v: str) -> str:
        v = (v or "native").strip().lower()
        if v not in ("native", "external"):
            raise ValueError("ABOS_DEFAULT_AGENT_BACKEND must be 'native' or 'external'")
        return v

    @field_validator("public_api_base_url", "web_base_url")
    @classmethod
    def _normalize_base_url(cls, v: str) -> str:
        # Tolerate a scheme-less or trailing-slashed value so the OAuth redirect
        # URI we build always matches the one registered on the Google client.
        return normalize_base_url(v)

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
