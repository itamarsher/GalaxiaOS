# Managed OpenClaw Gateway (internal-agent runtime)

The default hosted runtime for `external`-bound function slots (RFC 0001 §5).
Galaxia's `OpenClawWorker` drives it over OpenClaw's **OpenAI-compatible HTTP API**
— `POST /v1/chat/completions`, `Authorization: Bearer <token>`, target agent chosen
by the `model` field (`openclaw/<agentId>`).

We build **from the official upstream image** (`ghcr.io/openclaw/openclaw`, MIT) and
bake one config file (`config/openclaw.json`) on top — nothing else. The config:

- **enables the OpenAI API** (`gateway.http.endpoints.chatCompletions.enabled` — it
  is **off by default** in OpenClaw),
- **binds** `0.0.0.0:18789`,
- requires **token auth** (`gateway.auth.token: "${OPENCLAW_GATEWAY_TOKEN}"`), and
- defines a default agent.

Secrets are never baked in: the token is interpolated from the environment (a
missing `OPENCLAW_GATEWAY_TOKEN` fails config load, so the gateway **never boots
unauthenticated** — fail closed), and the model-provider key is read from
`ANTHROPIC_API_KEY`.

## Security posture — two deployment shapes

| | Public web service (free tier) | Private service (paid, `pserv`) |
|---|---|---|
| Network | Has a public URL | **No public URL** — private network only |
| Auth | **Bearer token** on every request | Bearer token **+** network isolation |
| Blueprint | `render.free.yaml` | `render.yaml` |

On free tier there are no private services, so the gateway is a normal public web
service and **the bearer token is the security boundary** (defense-in-depth). For a
truly internal-only gateway (unreachable from the internet at all), the paid
`render.yaml` runs it as a `pserv` reachable only from `abos-api`/`abos-worker`.

## The one operator input

Pin **`OPENCLAW_IMAGE`** (a Docker build ARG in `Dockerfile`) to a specific upstream
tag/digest in prod — e.g. `ghcr.io/openclaw/openclaw:2026.2.26`, or the `-browser`
variant if agents need OpenClaw's sandboxed browser tool. `:latest` is fine to
start.

## Secrets

| Env var | What |
|---|---|
| `OPENCLAW_GATEWAY_TOKEN` | The bearer every request must carry. Generated on the service and shared to `abos-api` (and `abos-worker`) as `ABOS_OPENCLAW_API_KEY`, so it lives in one place. |
| `ANTHROPIC_API_KEY` | The LLM the personas reason with. |

## Turn it on

1. Deploy `abos-openclaw` (free web service via `render.free.yaml`, or the `pserv`
   via `render.yaml`). Set `ANTHROPIC_API_KEY`.
2. Set `ABOS_OPENCLAW_BASE_URL` on `abos-api` (+ `abos-worker` on paid) to the
   gateway's address — `https://abos-openclaw.onrender.com` (public) or
   `http://abos-openclaw:18789` (private). `ABOS_OPENCLAW_API_KEY` is auto-shared.
3. Make it the default for newly generated functions (optional): set
   `ABOS_DEFAULT_AGENT_BACKEND=external` (RFC §5). Otherwise it's opt-in per agent
   via the founder's runtime toggle.

**Persona routing (§6 isolation):** the config registers **one isolated agent per
function** (`growth`, `product`, finance`, … each with its own workspace), and
Galaxia routes `model=openclaw/<function>` — so functions never share a
workspace/memory. OpenClaw serves only statically-defined agents and rejects `:`/`/`
in an id, so routing is function-level. **Full per-`(company, function)` isolation
across many companies** needs the Gateway's agent roster generated from Galaxia's
org (add an entry per external-bound agent) — a follow-up; a single-company
deployment already gets full per-function isolation. To instead pin every function
to one agent, set `ABOS_OPENCLAW_MODEL=openclaw/default`.

## Verify

- Public: `curl https://abos-openclaw.onrender.com/v1/chat/completions -X POST` with
  no bearer → `401`; with `-H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN"` → it
  accepts the request. `GET /healthz` → `200`.
- Private (`pserv`): the service has no `onrender.com` URL; the same checks run from
  inside `abos-api`.

## Local development

`docker compose --profile gateway up` runs it on the compose network with **no
published port** (reachable only at `http://openclaw:18789`). Set
`OPENCLAW_GATEWAY_TOKEN` + `ANTHROPIC_API_KEY` in your `.env`.
