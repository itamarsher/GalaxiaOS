# Managed OpenClaw Gateway (internal-agent runtime)

The default hosted runtime for `external`-bound function slots (RFC 0001 §5). One
Gateway hosts one persistent **persona per `(company, function)`** (§6); Galaxia's
`OpenClawWorker` drives it over the OpenAI-compatible HTTP API
(`POST /v1/chat/completions`), routing each function with
`model = openclaw/<company_id>:<function>`.

## The security posture — internal only, and authenticated

Two independent layers, both required:

1. **No public route.** In production the Gateway runs as a Render **private
   service** (`render.yaml`, `type: pserv`). A private service has **no public URL
   at all** and is reachable only from other services in the same Render project
   over the private network — here, `abos-api` and `abos-worker` at
   `http://abos-openclaw:8080`. It is never exposed to the internet. Do **not**
   give this service a custom/public domain.
2. **Bearer auth as defense-in-depth.** The Gateway still requires
   `Authorization: Bearer <token>` on every request (`OPENCLAW_GATEWAY_TOKEN`).
   Galaxia sends the same value as `ABOS_OPENCLAW_API_KEY`. So even a request that
   somehow reached the private network without going through Galaxia is rejected.
   `entrypoint.sh` **fails closed**: the Gateway won't boot without the token.

The two together mean: only Galaxia's own API/worker, holding the shared token, on
the private network, can talk to the Gateway.

## The one operator input

Pin **`OPENCLAW_IMAGE`** (a Docker build ARG in the `Dockerfile`) to the exact
upstream OpenClaw Gateway image + tag (a digest in prod). Everything else in this
folder — auth, bind address, health check, persona routing — is fixed and
reviewable; only the runtime artifact is swapped in. After pinning, confirm the
`entrypoint.sh` launch flags and `config/gateway.toml` field names against that
version's docs (the security-relevant settings are the bind host and the bearer).

## Secrets (set as `sync:false` on the Render service)

| Env var | What |
|---|---|
| `OPENCLAW_GATEWAY_TOKEN` | The bearer Galaxia presents. Auto-generated + shared to `abos-api`/`abos-worker` as `ABOS_OPENCLAW_API_KEY` via `render.yaml`. Long random string. |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `OPENROUTER_API_KEY` | At least one — the LLM the personas reason with. |

## Turn it on

1. Deploy the `abos-openclaw` service from `render.yaml` (Blueprint apply, or add
   the service to an existing environment). Set the secrets above.
2. `ABOS_OPENCLAW_BASE_URL` (= `http://abos-openclaw:8080`) and
   `ABOS_OPENCLAW_API_KEY` are wired onto `abos-api`/`abos-worker` automatically by
   the blueprint — the push worker (`OpenClawWorker`) is now bound.
3. To make the Gateway the **default** binding for newly generated functions, set
   `ABOS_DEFAULT_AGENT_BACKEND=external` on `abos-api`/`abos-worker` (RFC §5). Until
   then it's opt-in per agent via the founder's runtime toggle.

## Verify it's internal-only

- The `abos-openclaw` service has **no `onrender.com` URL** in the Render dashboard
  (private services don't get one). Confirm there is no public domain attached.
- From your laptop, the Gateway is unreachable (there is no public address to hit).
- From a shell **inside** `abos-api`/`abos-worker`:
  - `curl -s http://abos-openclaw:8080/v1/models` **without** the bearer → `401`.
  - the same **with** `-H "Authorization: Bearer $ABOS_OPENCLAW_API_KEY"` → `200`.

## Local development

`docker-compose.yml` includes an `openclaw` service on the compose network with
**no published port** (no `ports:` mapping), so it's reachable only from the other
compose services at `http://openclaw:8080` — the same internal-only shape as prod.
Set `OPENCLAW_GATEWAY_TOKEN` + a provider key in your `.env`.
