"""Orchestration: launch a company and dispatch tasks to agent backends.

Topology is hierarchical with the CEO as root planner. The CEO decomposes the
mission and dispatches to functional agents via the ``dispatch_task`` tool; the
Governance agent is not in the dispatch chain — it acts as a policy interceptor
on every tool call (see :mod:`app.services.governance`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import set_tenant
from app.models import Agent, AgentRun, CircuitBreaker, Company, Task
from app.models.enums import (
    AgentRole,
    AgentStatus,
    BreakerState,
    BreakerType,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime import breakers
from app.runtime.backends import get_backend
from app.runtime.context import RuntimeContext
from app.services import budget as budget_svc
from app.services import tasks as task_svc

#: Task statuses that mean the run is still doing (or waiting to do) work.
#: ``auditing`` counts as active: a delegated result is parked there pending the
#: CEO's review, so the run must not be declared finished while audits are open.
_ACTIVE_TASK_STATUSES = (
    TaskStatus.queued,
    TaskStatus.running,
    TaskStatus.waiting_approval,
    TaskStatus.auditing,
)


async def _create_ceo_run(
    db: AsyncSession,
    company_id: uuid.UUID,
    *,
    trigger: RunTrigger,
    goal: str,
    loop_seed: str,
    task_input: dict | None = None,
) -> uuid.UUID | None:
    """Create a root run + CEO root task. Returns the CEO task id to enqueue."""
    ceo = await db.scalar(
        select(Agent).where(Agent.company_id == company_id, Agent.role == AgentRole.ceo)
    )
    if ceo is None:
        return None

    run = AgentRun(company_id=company_id, trigger=trigger, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id

    task = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=ceo.id,
        depth=0,
        goal=goal,
        input=task_input,
        status=TaskStatus.queued,
        loop_signature=breakers.loop_signature(ceo.id, loop_seed),
    )
    db.add(task)
    await db.flush()
    return task.id


async def create_launch_run(db: AsyncSession, company_id: uuid.UUID) -> uuid.UUID | None:
    """Create the root run + CEO task. Returns the CEO task id to enqueue.

    The launch run starts with a plan-approval phase: the CEO drafts a high-level
    plan and submits it to the founder (``submit_plan``) before any functional
    work is dispatched. The ``requires_plan_approval`` flag enforces that gate in
    ``dispatch_task``.
    """
    return await _create_ceo_run(
        db,
        company_id,
        trigger=RunTrigger.onboarding,
        goal=(
            "Plan the company's execution, then run it. FIRST, draft a concise "
            "high-level plan: for each objective, the 1-3 initiatives you will "
            "pursue and which functional agent owns each. Call `submit_plan` with "
            "that plan and wait for the founder's approval. ONLY after the founder "
            "approves may you dispatch the initiatives to the functional agents."
        ),
        loop_seed="execute mission",
        task_input={"requires_plan_approval": True},
    )


async def create_scheduled_run(db: AsyncSession, company_id: uuid.UUID) -> uuid.UUID | None:
    """Create a recurring business-cycle run + CEO task. Returns the CEO task id."""
    # Time-varying loop seed so successive cycles aren't flagged as a repeat.
    loop_seed = f"business cycle {datetime.now(UTC).isoformat()}"
    return await _create_ceo_run(
        db,
        company_id,
        trigger=RunTrigger.scheduled,
        goal=(
            "Run a business cycle: review the latest real-world metrics and memory, "
            "assess progress toward objectives, and dispatch the next highest-leverage "
            "initiatives."
        ),
        loop_seed=loop_seed,
    )


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
    try:
        result = await backend.run(ctx, agent, task)
    except Exception as exc:  # noqa: BLE001
        # A task is flipped to ``running`` before dispatch; if the backend raises
        # (provider/network error, a bug, …) we must not leave it orphaned in
        # ``running`` — the run gate skips anything that isn't queued/waiting, so
        # it could never recover. For a task the CEO delegated, hand the failure to
        # the CEO to decide whether it's transient (re-run) or persistent (abandon);
        # otherwise mark it failed (visible, terminal).
        error_text = f"{type(exc).__name__}: {exc}"[:1000]
        review_task_id: uuid.UUID | None = None
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            row = await db.get(Task, task.id)
            if row is not None and row.status is TaskStatus.running:
                agent_row = await db.get(Agent, row.agent_id) if row.agent_id else None
                if agent_row is not None and await task_svc.should_review_failure(
                    db, agent=agent_row, task=row
                ):
                    review_task_id = await task_svc.begin_failure_review(
                        db, child_id=row.id, output={"error": error_text}
                    )
                if review_task_id is None:
                    row.status = TaskStatus.failed
                    row.output = {"error": error_text}
                    row.transcript = None  # terminal: drop the working-memory checkpoint
                await db.commit()
        if review_task_id is not None:
            # Handled gracefully: the CEO will decide on a retry. Don't re-raise.
            await ctx.enqueue_task(review_task_id)
            return {"status": TaskStatus.auditing.value, "output": {"error": error_text}}
        raise

    # Keep the org alive: if this task completing means the whole run is now
    # finished (nothing queued/running/awaiting the founder), automatically start
    # the next business cycle. Without this the org goes quiet after its first
    # burst of work until the once-a-day cron fires.
    await _maybe_continue_cycle(ctx, company_id=task.company_id, root_run_id=task.root_run_id)
    return result


async def has_active_tasks(db: AsyncSession, company_id: uuid.UUID) -> bool:
    """True if the company has any task still queued/running/awaiting the founder."""
    count = await db.scalar(
        select(func.count(Task.id)).where(
            Task.company_id == company_id, Task.status.in_(_ACTIVE_TASK_STATUSES)
        )
    )
    return bool(count and count > 0)


async def _maybe_continue_cycle(
    ctx: RuntimeContext, *, company_id: uuid.UUID, root_run_id: uuid.UUID
) -> None:
    """Start the next cycle once the current run has fully wound down.

    Idempotent under races: the finishing task that first flips the run row to
    ``done`` (under ``FOR UPDATE``) is the only one that enqueues the next cycle,
    so concurrent finishers can't double-launch it.
    """
    if not (settings.business_cycle_enabled and settings.business_cycle_continuous):
        return

    next_task_id: uuid.UUID | None = None
    async with ctx.session_factory() as db:
        await set_tenant(db, company_id)

        # Anything in this run still active? Then the run isn't finished yet.
        active = await db.scalar(
            select(func.count(Task.id)).where(
                Task.root_run_id == root_run_id, Task.status.in_(_ACTIVE_TASK_STATUSES)
            )
        )
        if active and active > 0:
            return

        # Claim the run: only the first finisher flips it to done and continues.
        run = await db.scalar(
            select(AgentRun).where(AgentRun.id == root_run_id).with_for_update().limit(1)
        )
        if run is None or run.status is not RunStatus.running:
            return
        run.status = RunStatus.done
        await db.flush()

        if await _can_continue(db, company_id):
            next_task_id = await create_scheduled_run(db, company_id)
        await db.commit()

    if next_task_id is not None:
        await ctx.enqueue_task(
            next_task_id, delay_seconds=settings.business_cycle_interval_seconds
        )


async def _can_continue(db: AsyncSession, company_id: uuid.UUID) -> bool:
    """Gate auto-continuation on company health: active, un-tripped, with budget."""
    company = await db.get(Company, company_id)
    if company is None or company.status is not CompanyStatus.active:
        return False

    spend_tripped = await db.scalar(
        select(CircuitBreaker.id).where(
            CircuitBreaker.company_id == company_id,
            CircuitBreaker.type == BreakerType.spend,
            CircuitBreaker.state == BreakerState.tripped,
        )
    )
    if spend_tripped is not None:
        return False

    budget = await budget_svc.get_active_budget(db, company_id)
    if budget is None:
        return False
    remaining = budget.limit_cents - budget.spent_cents - budget.reserved_cents
    return remaining >= settings.business_cycle_min_budget_cents
