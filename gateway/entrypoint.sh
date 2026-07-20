#!/usr/bin/env sh
# Fail-closed entrypoint for the managed OpenClaw Gateway (RFC 0001 §5).
#
# Refuses to start the Gateway unless it can enforce auth and actually run a model:
#   1. OPENCLAW_GATEWAY_TOKEN must be set — it is the bearer Galaxia presents and
#      the Gateway requires. Without it the Gateway would accept unauthenticated
#      requests from anything that reached the private network; we abort instead.
#   2. At least one model-provider key must be present, or every persona's LLM call
#      would fail at runtime — better to fail visibly at boot.
#
# The Gateway binds 0.0.0.0:$OPENCLAW_PORT. That is safe ONLY because the process
# runs as a Render private service with no public route (see render.yaml); binding
# all interfaces on the private network is what lets abos-api / abos-worker reach
# it at http://abos-openclaw:$OPENCLAW_PORT. Do not give this service a public
# domain.
set -eu

: "${OPENCLAW_PORT:=8080}"

if [ -z "${OPENCLAW_GATEWAY_TOKEN:-}" ]; then
  echo "FATAL: OPENCLAW_GATEWAY_TOKEN is unset — refusing to start an unauthenticated Gateway." >&2
  exit 1
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${OPENAI_API_KEY:-}" ] && [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "FATAL: no model-provider key set (ANTHROPIC_API_KEY | OPENAI_API_KEY | OPENROUTER_API_KEY)." >&2
  exit 1
fi

echo "Starting OpenClaw Gateway on 0.0.0.0:${OPENCLAW_PORT} (private network only; bearer auth required)."

# Hand off to the upstream OpenClaw Gateway entrypoint. The exact invocation
# depends on the pinned OPENCLAW_IMAGE; confirm the flag names against that
# version's `openclaw gateway --help`. `exec` so the Gateway is PID 1 and receives
# signals directly. Common shape:
exec openclaw gateway \
  --config /etc/openclaw/gateway.toml \
  --host 0.0.0.0 \
  --port "${OPENCLAW_PORT}"
