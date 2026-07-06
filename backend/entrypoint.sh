#!/usr/bin/env sh
# Free-tier entrypoint (used by render.free.yaml's dockerCommand).
#
# Render's free web instances have no preDeployCommand, so migrations run here
# at container start, then uvicorn launches the API — which also runs the arq
# worker in-process when ABOS_RUN_WORKER_IN_PROCESS=true. `alembic upgrade head`
# is idempotent, so re-running it on every cold start is a no-op once current.
#
# The paid render.yaml runs migrations via preDeployCommand and keeps the
# Dockerfile's default uvicorn CMD, so it never uses this script.
set -e

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
