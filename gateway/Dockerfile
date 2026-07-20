# Managed OpenClaw Gateway — the internal-agent runtime for `external`-bound
# functions (RFC 0001 §5). Galaxia's `OpenClawWorker` drives it over OpenClaw's
# OpenAI-compatible HTTP API (`POST /v1/chat/completions`); each business function
# routes to its own persona via `model=openclaw/<company_id>:<function>` (§6).
#
# This image is deployed as a Render PRIVATE SERVICE (see render.yaml,
# `type: pserv`): it has NO public URL and is reachable only from abos-api /
# abos-worker over Render's private network. The bearer token below is a second,
# independent layer — even inside the private network, an unauthenticated request
# is rejected.
#
# OPERATOR INPUT (the one thing to confirm): pin OPENCLAW_IMAGE to the exact
# upstream OpenClaw Gateway image + tag you intend to run. It's a build ARG so the
# rest of this scaffold — auth, bind, health, persona routing — is fixed and
# reviewable, and only the runtime artifact is swapped in. Pin a digest in prod.
ARG OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest
FROM ${OPENCLAW_IMAGE}

# Config template + entrypoint. The entrypoint refuses to start unless the bearer
# token and at least one model-provider key are present, so a misconfigured
# Gateway fails closed rather than coming up unauthenticated.
COPY config/gateway.toml /etc/openclaw/gateway.toml
COPY entrypoint.sh /usr/local/bin/gateway-entrypoint.sh
RUN chmod +x /usr/local/bin/gateway-entrypoint.sh

# Internal port only; Render's private service exposes it on the private network,
# never to the internet. Kept as an ARG->ENV so it stays in sync with render.yaml.
ENV OPENCLAW_PORT=8080
EXPOSE 8080

# Liveness: the OpenAI-compatible models endpoint should answer once the Gateway
# is up. Try curl or wget — whichever the base image ships.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD sh -c 'curl -fsS "http://127.0.0.1:${OPENCLAW_PORT}/v1/models" >/dev/null 2>&1 || wget -q -O /dev/null "http://127.0.0.1:${OPENCLAW_PORT}/v1/models"' || exit 1

ENTRYPOINT ["/usr/local/bin/gateway-entrypoint.sh"]
