"""arq worker: wires the RuntimeContext and exposes the ``run_task`` job."""

from __future__ import annotations

import uuid

from app.db import SessionLocal
from app.providers.registry import get_provider
from app.runtime import orchestrator
from app.runtime.context import RuntimeContext
from app.runtime.cost_meter import CostMeter
from app.runtime.queue import redis_settings


async def run_task(ctx: dict, task_id: str) -> dict:
    rc: RuntimeContext = ctx["runtime"]
    return await orchestrator.run_task(rc, uuid.UUID(task_id))


async def startup(ctx: dict) -> None:
    redis = ctx["redis"]

    async def enqueue_task(task_id: uuid.UUID) -> None:
        await redis.enqueue_job("run_task", str(task_id))

    ctx["runtime"] = RuntimeContext(
        session_factory=SessionLocal,
        cost_meter=CostMeter(SessionLocal),
        provider=get_provider("anthropic"),
        enqueue_task=enqueue_task,
    )


class WorkerSettings:
    functions = [run_task]
    on_startup = startup
    redis_settings = redis_settings()
    max_jobs = 10
