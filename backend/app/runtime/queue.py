"""arq queue helpers shared by the API (producer) and worker (consumer)."""

from __future__ import annotations

import uuid

from arq import create_pool
from arq.connections import RedisSettings

from app.config import settings


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(settings.redis_url)


async def enqueue_task(task_id: uuid.UUID, *, delay_seconds: float = 0) -> None:
    """Enqueue a task for the worker from outside the worker process (the API)."""
    pool = await create_pool(redis_settings())
    try:
        # Deterministic job id (the task id) makes re-enqueueing idempotent: arq
        # dedupes a job whose id is already queued, so startup recovery can safely
        # re-enqueue tasks already in flight without double-running them.
        await pool.enqueue_job(
            "run_task",
            str(task_id),
            _job_id=str(task_id),
            _defer_by=delay_seconds if delay_seconds > 0 else None,
        )
    finally:
        await pool.close()
