# ABOS — Autonomous Business Operating System

> *"What's your mission? What's your budget? Launch."* — everything else is generated.

A founder defines a **Mission**, **Constraints**, and **Budget**. ABOS generates and runs a fleet
of AI agents (CEO, Growth, Research, Product, Finance, Governance) that operate the company
autonomously, under a hard budget and a governance layer. The founder acts as a board member, not
an operator.

## Architecture at a glance

- **Backend:** Python + FastAPI (`backend/app/api`), async SQLAlchemy 2.0, Postgres + pgvector.
- **Agent runtime:** `backend/app/runtime` — an `arq` worker running a think→act→observe loop.
- **AI (BYOK):** provider-agnostic `LLMProvider` (`backend/app/providers`); Anthropic/Claude at
  launch. Founders bring their own key, stored envelope-encrypted.
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
- **Live runtime**: native agent loop, CEO-as-planner orchestration, circuit breakers,
  declarative policy engine, founder decision inbox.
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
