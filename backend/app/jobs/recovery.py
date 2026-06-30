"""Restart safety: rebuild the ephemeral work queue from durable state.

The durable business state (companies, agents, tasks, runs, budgets, decisions,
memory) lives in Postgres and survives a restart. The work *queue*, however, is
arq-on-Redis and is ephemeral on this deployment — on restart the queue can be
empty, and any task left mid-flight is orphaned:

- ``orchestrator.run_task`` only proceeds for tasks that are ``queued`` or
  ``waiting_approval``; a task flipped to ``running`` when the process died is
  never picked up again, so it is stuck forever.
- The continuous business loop enqueues the next cycle as a deferred job; if the
  process dies that in-flight job is lost, leaving an otherwise-healthy company
  idle.

:func:`recover_pending_work` runs on worker startup. For each active company it
resets orphaned ``running`` tasks back to ``queued``, re-enqueues all queued
tasks (rebuilding the Redis queue), and re-arms the continuous loop for any
healthy company that has gone fully idle. Re-running a task that already ran once
is expected here, so enqueueing does NOT pin a deterministic job id; double
execution is instead prevented by ``run_task``'s status gate (it skips any task
not in queued/waiting_approval and flips it to running before dispatch).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import Protocol

from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal, set_tenant
from app.jobs.scheduled import _active_company_ids
from app.models import Task
from app.models.enums import TaskStatus
from app.runtime import orchestrator
from app.services import provider_balance


class _Enqueue(Protocol):
    def __call__(self, task_id: uuid.UUID, *, delay_seconds: float = 0) -> Awaitable[None]: ...


class _EnqueueRecheck(Protocol):
    def __call__(
        self, company_id: uuid.UUID, *, delay_seconds: float = 0
    ) -> Awaitable[None]: ...


async def recover_pending_work(
    enqueue: _Enqueue, enqueue_recheck: _EnqueueRecheck | None = None
) -> dict:
    """Rebuild the Redis work queue from durable Postgres state.

    ``enqueue`` is an async callable ``(task_id, *, delay_seconds=0) -> None``
    (the worker's ``enqueue_task``). Transactions are kept per-company, mirroring
    :mod:`app.jobs.scheduled``.

    ``enqueue_recheck`` re-arms the provider-balance re-check for any company that
    is paused for an empty provider account (its deferred re-check job was lost
    with the crash). Defaults to the real arq helper; injectable for tests.
    """
    if enqueue_recheck is None:
        from app.runtime.queue import enqueue_provider_balance_recheck

        enqueue_recheck = enqueue_provider_balance_recheck

    companies = 0
    requeued = 0
    restarted = 0

    for company_id in await _active_company_ids():
        companies += 1
        to_enqueue: list[uuid.UUID] = []
        restart_task_id: uuid.UUID | None = None
        rearm_recheck = False

        async with SessionLocal() as db:
            await set_tenant(db, company_id)

            # Orphaned by the crash: a task flipped to ``running`` before the
            # process died is never re-picked (the run gate skips it). Reset it to
            # ``queued`` so the gate re-picks it.
            orphaned = await db.scalars(
                select(Task).where(
                    Task.company_id == company_id, Task.status == TaskStatus.running
                )
            )
            for task in orphaned:
                task.status = TaskStatus.queued
            await db.flush()

            # Every task now queued (originally queued + just-reset) gets
            # re-enqueued to rebuild the Redis queue. waiting_approval / done /
            # failed / blocked are left untouched and not enqueued.
            queued = await db.scalars(
                select(Task.id).where(
                    Task.company_id == company_id, Task.status == TaskStatus.queued
                )
            )
            to_enqueue = list(queued)

            await db.commit()

        # Re-arm the continuous loop: a healthy company that went fully idle (its
        # deferred next-cycle job was lost with the crash) needs a fresh cycle.
        async with SessionLocal() as db:
            await set_tenant(db, company_id)
            if not await orchestrator.has_active_tasks(
                db, company_id
            ) and await orchestrator._can_continue(db, company_id):
                restart_task_id = await orchestrator.create_scheduled_run(db, company_id)
                await db.commit()
            # A company paused for an empty provider balance had its deferred
            # re-check lost with the crash; re-arm it so it can still auto-resume
            # (and resurface to the founder) once the balance is restored.
            elif await provider_balance.is_exhausted(db, company_id):
                rearm_recheck = True

        for task_id in to_enqueue:
            await enqueue(task_id)
            requeued += 1

        if restart_task_id is not None:
            await enqueue(
                restart_task_id, delay_seconds=settings.business_cycle_interval_seconds
            )
            restarted += 1

        if rearm_recheck:
            # Check promptly after restart (the balance may have been topped up
            # while the worker was down); the re-check reschedules itself on the
            # normal cadence if it's still empty.
            await enqueue_recheck(company_id, delay_seconds=0)

    return {"companies": companies, "requeued": requeued, "restarted": restarted}
