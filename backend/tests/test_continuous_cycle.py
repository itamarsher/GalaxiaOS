"""Continuous operation: the org auto-starts the next cycle when a run winds down.

Without this the company goes quiet after its first burst of work until the
once-a-day cron. These tests pin the continuation gate: it fires only when the
whole run is terminal, is idempotent under concurrent finishers, and respects
company health (active + budget).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.config import settings
from app.models import Agent, AgentRun, Budget, Company, Task
from app.models.enums import (
    AgentRole,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime import orchestrator
from tests.conftest import requires_db


class _Ctx:
    """Minimal RuntimeContext stand-in that records enqueue calls."""

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.enqueued: list[tuple[uuid.UUID, float]] = []

    async def enqueue_task(self, task_id, *, delay_seconds: float = 0) -> None:
        self.enqueued.append((task_id, delay_seconds))


async def _make_run(session_factory, company_id, *, task_status):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
        db.add(agent)
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=agent.id,
            goal="g",
            status=task_status,
        )
        db.add(task)
        await db.commit()
        return run.id


@requires_db
async def test_continues_when_run_is_finished(session_factory, company_with_budget):
    company_id = company_with_budget  # active, $100 budget
    run_id = await _make_run(session_factory, company_id, task_status=TaskStatus.done)
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(
        ctx, company_id=company_id, root_run_id=run_id
    )

    # The finished run is marked done and exactly one next cycle is enqueued,
    # deferred by the configured interval.
    assert len(ctx.enqueued) == 1
    assert ctx.enqueued[0][1] == settings.business_cycle_interval_seconds
    async with session_factory() as db:
        run = await db.get(AgentRun, run_id)
        assert run.status is RunStatus.done
        # A new scheduled run/task now exists.
        scheduled = await db.scalar(
            select(AgentRun).where(
                AgentRun.company_id == company_id, AgentRun.trigger == RunTrigger.scheduled
            )
        )
        assert scheduled is not None


@requires_db
async def test_does_not_continue_while_tasks_active(session_factory, company_with_budget):
    company_id = company_with_budget
    run_id = await _make_run(session_factory, company_id, task_status=TaskStatus.running)
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(
        ctx, company_id=company_id, root_run_id=run_id
    )

    assert ctx.enqueued == []
    async with session_factory() as db:
        run = await db.get(AgentRun, run_id)
        assert run.status is RunStatus.running  # left untouched


@requires_db
async def test_idempotent_under_double_finish(session_factory, company_with_budget):
    """Two finishers racing on the same finished run start the next cycle only once."""
    company_id = company_with_budget
    run_id = await _make_run(session_factory, company_id, task_status=TaskStatus.done)
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(ctx, company_id=company_id, root_run_id=run_id)
    await orchestrator._maybe_continue_cycle(ctx, company_id=company_id, root_run_id=run_id)

    assert len(ctx.enqueued) == 1


@requires_db
async def test_does_not_continue_when_out_of_budget(session_factory, company_with_budget):
    company_id = company_with_budget
    # Spend the whole budget so remaining is below the floor.
    async with session_factory() as db:
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
        budget.spent_cents = budget.limit_cents
        await db.commit()
    run_id = await _make_run(session_factory, company_id, task_status=TaskStatus.done)
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(ctx, company_id=company_id, root_run_id=run_id)

    # Run is still closed out, but no next cycle is started.
    assert ctx.enqueued == []
    async with session_factory() as db:
        run = await db.get(AgentRun, run_id)
        assert run.status is RunStatus.done


@requires_db
async def test_does_not_continue_when_company_paused(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        company.status = CompanyStatus.paused
        await db.commit()
    run_id = await _make_run(session_factory, company_id, task_status=TaskStatus.done)
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(ctx, company_id=company_id, root_run_id=run_id)
    assert ctx.enqueued == []
