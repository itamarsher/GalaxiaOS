# Production deployment & CI/CD

Target: **Render** (PaaS) with **managed Postgres + Redis**. CI/CD: **GitHub
Actions** → tests gate deploys, which fire via **Render Deploy Hooks**.

```
 push/PR ─▶ GitHub Actions CI ─┬─ backend: ruff · provider-guard · alembic upgrade · pytest (pgvector + redis services)
                               └─ frontend: tsc · next build
                                          │ (push to main, all green)
                                          ▼
                               deploy job ─▶ Render Deploy Hooks ─▶ api · worker · web
                                                                     (preDeploy: alembic upgrade head)
```

## Topology (see `render.yaml`)

| Render service | Type | Image | Notes |
|---|---|---|---|
| `abos-postgres` | managed Postgres 16 | — | pgvector created by the baseline migration |
| `abos-redis` | managed Key Value | — | rate limiting + arq queue |
| `abos-api` | web (docker) | `backend/Dockerfile` | `/health/ready` healthcheck; `preDeployCommand: alembic upgrade head` |
| `abos-worker` | worker (docker) | `backend/Dockerfile` | command `arq app.runtime.worker.WorkerSettings` |
| `abos-web` | web (docker) | `frontend/Dockerfile.prod` | `NEXT_PUBLIC_API_BASE_URL` baked at build |
| `abos-openclaw` | **private service** (docker) | `gateway/Dockerfile` | internal-agent runtime (RFC 0001 §5); **no public URL** — see below |

## First-time setup

1. **Apply the blueprint.** Render Dashboard → New → Blueprint → select this repo.
   It provisions Postgres, Redis, and the three services from `render.yaml`.
2. **Set secrets** (env vars marked `sync: false`):
   - `abos-api` / `abos-worker`: `ABOS_MASTER_KEY` — generate with `make gen-key`
     (32-byte base64url; in production source it from a KMS/secret manager).
     `ABOS_JWT_SECRET` is auto-generated and shared to the worker.
   - `abos-web`: `NEXT_PUBLIC_API_BASE_URL` = the `abos-api` URL
     (e.g. `https://abos-api.onrender.com`).
   - `ABOS_DATABASE_URL` / `ABOS_REDIS_URL` are wired automatically from the
     managed resources. The app normalizes a `postgres://…?sslmode=require` URL
     into an asyncpg URL (`app.config.normalize_db_url`), so the provider's
     connection string works as-is.
3. **Wire CI-gated deploys.** For each service, copy its **Deploy Hook** URL
   (Render → service → Settings → Deploy Hook) into GitHub repo secrets:
   `RENDER_DEPLOY_HOOK_API`, `RENDER_DEPLOY_HOOK_WORKER`, `RENDER_DEPLOY_HOOK_WEB`.
   Until these exist, the CI `deploy` job no-ops. `autoDeploy: false` keeps Render
   from deploying on raw pushes — only green CI on `main` triggers a release.

## Managed OpenClaw Gateway (internal-agent runtime)

The `abos-openclaw` service (`gateway/`, RFC 0001 §5) is the batteries-included
runtime for `external`-bound function slots. It is deployed as a Render **private
service** (`type: pserv`), which is the security boundary the design turns on:

- **Not externally accessible.** A private service has **no public URL** and is
  reachable only from other services in the project over Render's private network.
  `abos-api` / `abos-worker` reach it at `http://abos-openclaw:8080`; nothing on the
  internet can. Never attach a custom/public domain to it.
- **Authenticated even internally.** The Gateway requires
  `Authorization: Bearer <OPENCLAW_GATEWAY_TOKEN>` on every request; Galaxia sends
  the same value as `ABOS_OPENCLAW_API_KEY`. The blueprint generates the token on
  `abos-openclaw` and shares it to the callers via `fromService`, so the secret
  lives in one place. `gateway/entrypoint.sh` **fails closed** — no token, no boot.

Setup:

1. **Pin the image.** Set the `OPENCLAW_IMAGE` build ARG (in `gateway/Dockerfile`)
   to your chosen upstream OpenClaw Gateway image + tag (a digest in prod). This is
   the one operator input; everything else is fixed in `gateway/`.
2. **Set the provider secret(s)** on `abos-openclaw` (dashboard, `sync:false`):
   at least one of `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY`.
3. **It's wired automatically.** `ABOS_OPENCLAW_BASE_URL` (`http://abos-openclaw:8080`)
   and `ABOS_OPENCLAW_API_KEY` are set on `abos-api`/`abos-worker` by the blueprint,
   so the push worker is bound as soon as `abos-openclaw` is up.
4. **Make it the default (optional).** Set `ABOS_DEFAULT_AGENT_BACKEND=external` on
   `abos-api`/`abos-worker` to auto-bind newly generated functions to the Gateway
   (RFC §5); otherwise it's opt-in per agent via the founder's runtime toggle.

Verify it's internal-only: the service has no `onrender.com` URL; from inside
`abos-api`, `curl http://abos-openclaw:8080/v1/models` returns `401` without the
bearer and `200` with it. Full detail in `gateway/README.md`.

## Migrations

`abos-api`'s `preDeployCommand` runs `alembic upgrade head` before each release,
so schema changes apply automatically and a failed migration aborts the deploy.
CI also runs `alembic upgrade head` against a real `pgvector` service on every
PR, validating the whole migration chain (incl. the `vector` extension) before
merge.

## Scaling

- `abos-api` and `abos-web` scale horizontally (stateless). Set
  `ABOS_RATE_LIMIT_BACKEND=redis` (already in `render.yaml`) so the limiter is
  shared across instances.
- `abos-worker` can scale out; arq coordinates via Redis. The cron jobs (runway
  recompute, daily digest) are safe to run from a single worker.

## LLM models — Anthropic or open-source (BYOK)

The fleet is provider-agnostic: the LLM vendor is chosen by which key a founder
stores in **Settings** (BYOK, envelope-encrypted). No Render service or GPU is
required for any of these — the key is per-company, never a global env var.

- **Anthropic (Claude)** — the launch default (`sk-ant-…`).
- **Open-source models via a hosted aggregator** (recommended cheaper default):
  paste an **OpenRouter** (`sk-or-…`), **Groq** (`gsk_…`), or **Together** key in
  Settings. One key unlocks Llama 3.3, DeepSeek R1, Qwen, gpt-oss, etc. — served
  over OpenAI-compatible APIs. Typical OSS text models run **~$0.10–$1.20 / Mtok**
  vs Claude's $1–$25 / Mtok (Haiku→Opus), i.e. roughly **5–50× cheaper per token**,
  and cost $0 at idle. Endpoint URLs are baked in; **nothing in `render.yaml`
  changes.**
- **Self-hosted open-source models** (vLLM / Ollama / TGI): run the model on an
  external GPU host (Render has no GPU tier), then set
  `ABOS_OPENAI_COMPAT_BASE_URL` + the three `ABOS_OPENAI_COMPAT_MODEL_*` slugs on
  `abos-api` **and** `abos-worker`; the founder stores that server's token under
  the `openai_compat` provider. Only worth it above ~50–100M tokens/month
  sustained (or when privacy forces on-prem); below that a hosted aggregator is
  cheaper and simpler.

Steer founders to tool-calling + JSON-capable OSS models (Llama 3.3, DeepSeek
V3/R1, Qwen3, gpt-oss) — the agent loop relies on structured output. Model slugs
and prices in `backend/app/providers/oss.py` are best-effort snapshots
(overridable per-agent via `Agent.model_pref`); real spend always reconciles from
`usage` after each call.

## Security follow-ups

- **Master key in KMS.** `ABOS_MASTER_KEY` wraps every BYOK provider key
  (envelope encryption). In production, source it from a managed secret store and
  rotate per the envelope scheme.
- **Strict RLS.** Row-Level Security is enabled and every tenant path sets the
  `app.current_company` GUC; the policy is still permissive-when-unset. Once
  verified end-to-end, ship the strict-policy migration (see `app/db.py`).
- **CORS.** Restrict to the web origin in production via
  `ABOS_CORS_ALLOW_ORIGINS` (comma-separated; defaults to `*`). Set it on
  `abos-api` to the `abos-web` URL, e.g. `https://abos-web.onrender.com`. CORS
  is the outermost middleware, so rate-limit (429) and error responses also
  carry the `Access-Control-*` headers — without that, the browser masks the
  real status with an opaque "No 'Access-Control-Allow-Origin' header" error.

## Alternatives

The same shape maps to Fly.io (`fly.toml` per app + Fly Managed Postgres +
Upstash Redis) or Railway. Only the manifest format changes — Dockerfiles, the
migration pre-deploy step, and the CI workflow are reusable.
