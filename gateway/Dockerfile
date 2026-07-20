# Managed OpenClaw Gateway — the internal-agent runtime for `external`-bound
# functions (RFC 0001 §5). Galaxia's `OpenClawWorker` drives it over OpenClaw's
# OpenAI-compatible HTTP API (`POST /v1/chat/completions`, `Authorization: Bearer
# <OPENCLAW_GATEWAY_TOKEN>`, agent selected by `model=openclaw/<agentId>`).
#
# We build FROM the official upstream image and only bake our gateway config on top
# — the config enables the OpenAI API (off by default), binds the gateway, and
# wires token auth. Verified against docs.openclaw.ai (Docker install +
# configuration-reference).
#
# OPERATOR INPUT: pin OPENCLAW_IMAGE to a specific upstream tag/digest in prod
# (e.g. ghcr.io/openclaw/openclaw:2026.2.26, or the -browser variant if agents need
# the sandboxed browser tool). `:latest` is fine to start.
ARG OPENCLAW_IMAGE=ghcr.io/openclaw/openclaw:latest
FROM ${OPENCLAW_IMAGE}

# Bake the config and point OpenClaw at it. Secrets stay in the environment: the
# config interpolates ${OPENCLAW_GATEWAY_TOKEN} (a missing var fails config load, so
# the gateway never boots unauthenticated — fail closed), and the model-provider key
# is read from ANTHROPIC_API_KEY.
COPY config/openclaw.json /etc/openclaw/openclaw.json
ENV OPENCLAW_CONFIG_PATH=/etc/openclaw/openclaw.json

# The gateway (WS + HTTP multiplex, incl. the OpenAI API) listens on 18789.
EXPOSE 18789

# Liveness against OpenClaw's own health endpoint (curl or wget, whichever ships).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD sh -c 'curl -fsS "http://127.0.0.1:18789/healthz" >/dev/null 2>&1 || wget -q -O /dev/null "http://127.0.0.1:18789/healthz"' || exit 1

# Do NOT override the upstream entrypoint — the base image already starts the
# gateway, which reads OPENCLAW_CONFIG_PATH.
