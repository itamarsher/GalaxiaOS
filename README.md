# ABOS — Autonomous Business Operating System

> *"What's your mission? What's your budget? Launch."* — everything else is generated.

A founder defines a **Mission**, **Constraints**, and **Budget**. ABOS designs a company to fit
that mission — generating a fleet of AI agents whose roles, responsibilities, and budgets are
derived from what the business actually needs (e.g. CEO, Growth, Research, Product, Finance,
Governance), guaranteeing the oversight roles, and reshaping as objectives evolve. The fleet
operates the company autonomously, under a hard budget and a governance layer. The founder acts as
a board member, not an operator.

## Mission

**Enable any person on the planet to own or create autonomous businesses.** The core product is
**free and open-source** with a BYOK (bring-your-own-key) implementation — owning or creating an
autonomous business shouldn't depend on a subscription or a gatekeeper. See [`docs/MISSION.md`](docs/MISSION.md)
for the full statement and how we plan to sustain the open core.

## Architecture at a glance

- **Backend:** Python + FastAPI (`backend/app/api`), async SQLAlchemy 2.0, Postgres + pgvector.
- **Agent runtime:** `backend/app/runtime` — an `arq` worker running a think→act→observe loop.
- **AI (BYOK or managed):** provider-agnostic `LLMProvider` (`backend/app/providers`);
  Anthropic/Claude or **open-source models** (Llama 3.3, DeepSeek R1, Qwen, gpt-oss) via
  OpenAI-compatible hosts (OpenRouter/Groq/Together, or a self-hosted vLLM/Ollama server) —
  typically far cheaper per token. Founders bring their own key, stored envelope-encrypted — or,
  on a **hosted deployment with managed mode on**, bring *nothing*: the platform funds a free tier
  of compute that converts to paid managed usage (see *Managed mode* below).
- **Budget OS:** every billable action (LLM tokens **and** external charges like domains) passes
  through one chokepoint — `CostMeter` (`backend/app/runtime/cost_meter.py`) — which reserves
  against the budget *before* spending.
- **Frontend:** Next.js (App Router) + TypeScript (`frontend/`).

Two decoupling seams keep the system future-proof:
1. **`LLMProvider`** — which model vendor answers (Anthropic now; OpenAI/Gemini later).
2. **`AgentBackend`** — how an agent executes (native loop now; external/marketplace agents later).

See the full design in the plan referenced from the project history.

## Status

- **Onboarding → launch**: mission → objectives/OKRs → generated agent fleet → launch.
- **Budget OS**: every billable action (LLM + external) metered through one `CostMeter`
  chokepoint; per-category/per-agent rollups; runway forecasting; ROI-based pausing.
- **Real external spend (Stripe)**: optional payment seams give an agent real money,
  two ways. (1) **Stripe Issuing** — a budget-controlled virtual card funds a registrar
  account (Base44-style reseller model), then the agent buys real domains via the
  `namecheap` API; authorizations are approved *programmatically* (no human per charge)
  by the `/webhooks/stripe/issuing` real-time-auth webhook, which only clears spend
  inside the company's remaining budget, and the registrar fails *before* the
  irreversible call when the balance is short. (2) **Stripe Link** — an agent mints a
  scoped, single-purchase Shared Payment Token a Stripe-enabled seller charges (the
  `card_checkout` registrar). Each is off until its provider is selected (a key +
  `ABOS_DOMAIN_REGISTRAR`/`ABOS_PAYMENT_WALLET`); a live Stripe key moves real money,
  bounded by the same `CostMeter` reserve→commit path so the budget is reserved
  before any charge.
- **Live runtime**: native agent loop, CEO-as-planner orchestration, circuit breakers,
  declarative policy engine, founder decision inbox.
- **End-of-cycle retrospective**: before each business cycle closes, the CEO runs a
  retrospective — every agent that did work reflects (what went right/wrong, and only
  *impactful* improvement suggestions, targeting anything in its context: memory,
  playbook, directives, skills, or missing tools). The CEO ingests them and decides
  what to implement now with its own levers (playbook/directive/memory) versus route to
  the Platform agent as a `request_capability`. Agents are told a genuinely empty
  retrospective beats padded filler.
- **External-comms index & approval gate**: every outbound message the fleet sends
  (email, social post, published page, ad, notification) is indexed at the agent
  loop's tool chokepoint into one auditable log. A toggleable governance policy
  (`is_external` rule) can require founder sign-off on *every* external message —
  it lands in the decision inbox, discussable with full context, before it goes out.
- **Governance & reputation**: per-agent trust/accuracy/ROI/reliability updated on task
  completion (also the future marketplace trust signal).
- **Company Memory**: pgvector-backed write/retrieve behind a swappable embedding seam.
- **Founder Copilot**: daily digest (cron) + NL control plane — LLM answers grounded
  queries and parses commands into allow-listed, code-executed actions.

Tests: `make test` (set `ABOS_TEST_DATABASE_URL` to a Postgres DSN to include the
DB-backed budget/runway/reputation tests; pure-logic tests run without a DB).

## Quickstart

```bash
cp .env.example .env          # set ABOS_MASTER_KEY and DB creds
make dev                      # postgres + redis + api + worker + web (docker-compose)
make migrate                  # apply Alembic migrations
```

Backend only (no docker):

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Open the API docs at http://localhost:8000/docs and the web app at http://localhost:3000.

## Managed mode (hosted "no keys needed" tier)

The core is BYOK, and **self-hosting stays strictly BYOK** — `ABOS_MANAGED_MODE_ENABLED`
defaults to `false`, so nobody's key is ever shared unless an operator opts in. A **hosted**
deployment can flip it on to let a founder launch with *zero* keys:

- **One resolution seam.** `apikeys.resolve_active_provider` returns the founder's own stored
  key first (BYOK always wins and is never metered against the platform); otherwise, under
  managed mode, the shared `ABOS_PLATFORM_LLM_*` key — but only while the founder is *eligible*.
  The same "BYO first, else platform default" pattern already governs the read-only capabilities
  (web search, media-gen), now gated by managed eligibility too.
- **Two-dimension accounting.** `CostMeter` still reserves/commits every action against the
  company's own business budget exactly as before. When the funding source is the platform, it
  *additionally* records the committed spend to a per-founder **platform ledger**
  (`platform_billing_accounts` / `platform_charges`, keyed by `user_id` and pooled across all a
  founder's companies) inside the same transaction — so LLM tokens and paid capabilities funnel
  through one place.
- **Free tier → paid managed.** Each founder gets `ABOS_PLATFORM_FREE_TIER_CENTS` of
  platform-funded compute (with a per-day burst cap). Cross it and managed capabilities stop with
  a clear "add your own key or upgrade" reason. Upgrading starts a Stripe metered-subscription
  Checkout (`ABOS_STRIPE_MANAGED_PRICE_ID`); `checkout.session.completed` promotes the account and
  subsequent platform spend is reported as usage (× `ABOS_MANAGED_BILLING_MARKUP`).
- **Abuse guardrails.** The free tier is pooled **per founder account** (new companies can't
  multiply it), a daily cap bounds bursts, and a cheap deterministic mission screen
  (`services/screening.py`) gates clearly-disallowed free-tier missions (BYOK founders are exempt).

Onboarding drops the hard key gate: with managed mode on, Step 2 leads with "launch — no keys
needed" and demotes the key inputs to an optional *Advanced* disclosure. Settings shows the
managed meter and the upgrade CTA.

## Security hardening (RLS)

The `company_id` tenant boundary is enforced at the service/query layer (every
query filters on the company resolved by `CompanyDep`). As defense-in-depth,
Postgres **Row-Level Security** is enabled on every tenant table (migration
`0002_row_level_security`), keyed to the `app.current_company` session GUC and
`FORCE`d so it applies even to the table-owner role the app connects as.

DB-level scoping is now **active**: `app.db.set_tenant(session, company_id)`
(transaction-scoped `set_config`, so it never leaks across pooled connections) is
called on every tenant path — the `CompanyDep`/SSE API dependencies, the agent
runtime (orchestrator, native + marketplace backends), the `CostMeter` sessions,
and the scheduled jobs. The policy is still **permissive-when-unset** (it allows
all rows if the GUC is absent) so that global/non-tenant sessions and tests keep
working; because the app role is not a superuser in production, this acts as a
real per-tenant boundary wherever the GUC is set. The remaining step is a
follow-up migration that drops the permissive fallback for a strict
`company_id = current_setting('app.current_company')::uuid`, once you've
confirmed no tenant-table access path is left un-scoped. See the `app.db` module
docstring for the procedure.

## Operations

- **Structured logging**: JSON logs (`ABOS_LOG_JSON`) with a per-request id —
  honors an inbound `X-Request-ID`, otherwise generates one, echoes it on the
  response, and binds it to every log line for the request (`app.observability`).
- **Rate limiting**: per-user (by bearer token) or per-IP fixed-window limit
  (`ABOS_RATE_LIMIT_PER_MINUTE`); `memory` backend for a single process, `redis`
  for multi-process deploys. `/health*` and docs are exempt. Over-limit → `429`
  with `Retry-After` (`app.ratelimit`).
- **Probes**: `GET /health` (liveness) and `GET /health/ready` (readiness —
  checks the database, returns `503` when unreachable).
- **Deploy**: `docker-compose.yml` is dev-oriented (Postgres+pgvector, Redis,
  api, worker, web). For production set `ABOS_RATE_LIMIT_BACKEND=redis`, a real
  `ABOS_MASTER_KEY` from a KMS, and run the API and `arq` worker as separate
  scaled services. A production manifest (k8s/Compose-prod) is a follow-up.

### Render blueprints (paid vs. free)

Two Render Blueprints are provided:

- **`render.yaml`** — production topology: managed Postgres + Redis and
  separate API, worker, and web services (~$40/mo).
- **`render.free.yaml`** — experiment for **$0/mo**. Render has no free
  background-worker plan and deletes free Postgres after 30 days, so this
  variant:
  - folds the worker into the API process via `ABOS_RUN_WORKER_IN_PROCESS=true`
    (the API runs the arq loop + cron jobs in-process — see `app.main` lifespan);
  - uses a free, persistent **[Neon](https://neon.tech)** Postgres for
    `ABOS_DATABASE_URL` (pgvector supported; `normalize_db_url` handles its
    SSL params), since Render's free database self-deletes;
  - uses a free Render Key Value (Redis) for the ephemeral arq queue.

  Free web services spin down after ~15 min idle, so the first request after
  idle is slow and cron jobs only run while awake — fine for experimentation.
  Ping `/health` on a schedule to stay warm, or switch to `render.yaml` to scale
  up. `ABOS_RUN_WORKER_IN_PROCESS` is the only code-level seam between the two.

## Layout

```
backend/app/
  models/      SQLAlchemy ORM (company_id = tenant boundary)
  schemas/     Pydantic v2 DTOs
  api/         FastAPI routers
  services/    business logic
  providers/   LLM abstraction — ONLY place that imports a vendor SDK
  runtime/     agent execution: loop, orchestrator, cost_meter, backends, breakers
  crypto/      envelope encryption for BYOK keys
  jobs/        scheduled jobs (daily digest, runway recalc)
frontend/      Next.js App Router
```
