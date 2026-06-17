"""arq worker: wires the RuntimeContext and exposes the ``run_task`` job."""

from __future__ import annotations

import uuid

from arq import cron

from app.config import settings
from app.db import SessionLocal
from app.jobs.recovery import recover_pending_work
from app.jobs.scheduled import generate_digests, recompute_runway, run_business_cycle
from app.observability import get_logger
from app.providers.registry import get_provider
from app.runtime import orchestrator
from app.runtime.context import RuntimeContext
from app.runtime.cost_meter import CostMeter
from app.runtime.queue import redis_settings

_log = get_logger("abos.worker")


async def run_task(ctx: dict, task_id: str) -> dict:
    rc: RuntimeContext = ctx["runtime"]
    return await orchestrator.run_task(rc, uuid.UUID(task_id))


async def startup(ctx: dict) -> None:
    redis = ctx["redis"]

    async def enqueue_task(task_id: uuid.UUID, *, delay_seconds: float = 0) -> None:
        # NB: do NOT pin a deterministic ``_job_id`` here. arq retains a finished
        # job's result for a while and refuses to re-enqueue that id, which would
        # silently drop legitimate RE-runs of the same task — resuming a parked
        # task after a plan/budget approval, or recovering an orphaned task on
        # startup. Double-execution is already prevented in ``run_task`` (it skips
        # any task not in queued/waiting_approval and flips it to running first).
        await redis.enqueue_job(
            "run_task",
            str(task_id),
            _defer_by=delay_seconds if delay_seconds > 0 else None,
        )

    ctx["runtime"] = RuntimeContext(
        session_factory=SessionLocal,
        cost_meter=CostMeter(SessionLocal),
        provider=get_provider("anthropic"),
        enqueue_task=enqueue_task,
    )

    if settings.recover_on_startup:
        # Rebuild the ephemeral Redis queue from durable Postgres state. Best
        # effort: a recovery failure must not prevent the worker from booting.
        try:
            summary = await recover_pending_work(enqueue_task)
            _log.info("recover_pending_work", extra={"extra_fields": summary})
        except Exception:  # noqa: BLE001
            _log.exception("recover_pending_work_failed")


class WorkerSettings:
    functions = [run_task]
    cron_jobs = [
        cron(recompute_runway, minute=settings.runway_recompute_minute),
        cron(generate_digests, hour=settings.digest_hour_utc, minute=0),
        cron(run_business_cycle, hour=settings.business_cycle_hour_utc, minute=0),
    ]
    on_startup = startup
    redis_settings = redis_settings()
    max_jobs = 10


def build_worker(handle_signals: bool = True):
    """Construct an arq ``Worker`` from :class:`WorkerSettings`.

    ``handle_signals=False`` is required when embedding the worker inside the
    API process (uvicorn owns the signal handlers); see the API lifespan and
    the ``run_worker_in_process`` setting.
    """
    from arq.worker import create_worker

    return create_worker(WorkerSettings, handle_signals=handle_signals)
