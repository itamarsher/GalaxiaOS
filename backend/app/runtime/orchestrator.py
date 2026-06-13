"""Orchestration: launch a company and dispatch tasks to agent backends.

Topology is hierarchical with the CEO as root planner. The CEO decomposes the
mission and dispatches to functional agents via the ``dispatch_task`` tool; the
Governance agent is not in the dispatch chain — it acts as a policy interceptor
on every tool call (see :mod:`app.services.governance`).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import set_tenant
from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, AgentStatus, RunStatus, RunTrigger, TaskStatus
from app.runtime import breakers
from app.runtime.backends import get_backend
from app.runtime.context import RuntimeContext


async def create_launch_run(db: AsyncSession, company_id: uuid.UUID) -> uuid.UUID | None:
    """Create the root run + CEO task. Returns the CEO task id to enqueue."""
    ceo = await db.scalar(
        select(Agent).where(Agent.company_id == company_id, Agent.role == AgentRole.ceo)
    )
    if ceo is None:
        return None

    run = AgentRun(company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id

    task = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=ceo.id,
        depth=0,
        goal="Execute the company mission: decompose objectives and dispatch initiatives.",
        status=TaskStatus.queued,
        loop_signature=breakers.loop_signature(ceo.id, "execute mission"),
    )
    db.add(task)
    await db.flush()
    return task.id


async def run_task(ctx: RuntimeContext, task_id: uuid.UUID) -> dict:
    """Worker entrypoint for a single task: breaker-gate, then dispatch to backend."""
    async with ctx.session_factory() as db:
        task = await db.get(Task, task_id)
        if task is None:
            return {"status": "missing"}
        await set_tenant(db, task.company_id)
        if task.status not in (TaskStatus.queued, TaskStatus.waiting_approval):
            return {"status": f"skipped:{task.status.value}"}

        verdict = await breakers.check_before_task(db, task)
        if not verdict.ok:
            await breakers.block_task(db, task, verdict.reason or "blocked")
            await db.commit()
            return {"status": "blocked", "reason": verdict.reason}

        agent = await db.get(Agent, task.agent_id)
        if agent is None or agent.status is AgentStatus.paused:
            await breakers.block_task(db, task, "agent paused")
            await db.commit()
            return {"status": "blocked", "reason": "agent paused"}

        task.status = TaskStatus.running
        await db.commit()
        backend_type = agent.backend_type.value

    backend = get_backend(backend_type)
    return await backend.run(ctx, agent, task)
