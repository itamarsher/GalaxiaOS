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


async def _make_cycle_run(
    session_factory,
    company_id,
    *,
    functional_role=AgentRole.growth,
    functional_status=TaskStatus.done,
    with_retro_marker=False,
):
    """A wound-down *scheduled* cycle run: a done CEO task plus one functional task.

    When ``with_retro_marker`` is set, a completed CEO retrospective task is also
    present, simulating the second wind-down (retro already ran).
    """
    async with session_factory() as db:
        ceo = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
        func = Agent(company_id=company_id, role=functional_role, name="Fn")
        db.add_all([ceo, func])
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        db.add_all(
            [
                Task(
                    company_id=company_id, run_id=run.id, root_run_id=run.id,
                    agent_id=ceo.id, goal="plan cycle", status=TaskStatus.done,
                ),
                Task(
                    company_id=company_id, run_id=run.id, root_run_id=run.id,
                    agent_id=func.id, goal="do work", status=functional_status,
                ),
            ]
        )
        if with_retro_marker:
            db.add(
                Task(
                    company_id=company_id, run_id=run.id, root_run_id=run.id,
                    agent_id=ceo.id, goal="retro", status=TaskStatus.done,
                    input={"retrospective": True},
                )
            )
        await db.commit()
        return run.id


# ── End-of-cycle retrospective ──────────────────────────────────────────────────
def test_should_run_retrospective_decision() -> None:
    # Fires only for a scheduled cycle that hasn't retro'd yet and had real work.
    assert orchestrator._should_run_retrospective(
        enabled=True, trigger=RunTrigger.scheduled, retro_already_ran=False,
        worked_roles=["growth"],
    )
    # Not for the onboarding/launch run.
    assert not orchestrator._should_run_retrospective(
        enabled=True, trigger=RunTrigger.onboarding, retro_already_ran=False,
        worked_roles=["growth"],
    )
    # Not once the retro has already run (prevents recursion).
    assert not orchestrator._should_run_retrospective(
        enabled=True, trigger=RunTrigger.scheduled, retro_already_ran=True,
        worked_roles=["growth"],
    )
    # Not when no functional agent did work.
    assert not orchestrator._should_run_retrospective(
        enabled=True, trigger=RunTrigger.scheduled, retro_already_ran=False,
        worked_roles=[],
    )
    # Not when the feature is disabled.
    assert not orchestrator._should_run_retrospective(
        enabled=False, trigger=RunTrigger.scheduled, retro_already_ran=False,
        worked_roles=["growth"],
    )


@requires_db
async def test_scheduled_cycle_spawns_retrospective_before_closing(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    run_id = await _make_cycle_run(session_factory, company_id)
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(ctx, company_id=company_id, root_run_id=run_id)

    # The run is held OPEN and a CEO retrospective task is enqueued immediately —
    # the next cycle is NOT started yet.
    assert len(ctx.enqueued) == 1
    retro_task_id, delay = ctx.enqueued[0]
    assert delay == 0
    async with session_factory() as db:
        run = await db.get(AgentRun, run_id)
        assert run.status is RunStatus.running  # stays open for the retrospective
        retro = await db.get(Task, retro_task_id)
        assert retro.input == {"retrospective": True}
        assert retro.agent_id == await db.scalar(
            select(Agent.id).where(
                Agent.company_id == company_id, Agent.role == AgentRole.ceo
            )
        )
        # No next scheduled cycle yet.
        assert (
            await db.scalar(
                select(AgentRun).where(
                    AgentRun.company_id == company_id,
                    AgentRun.trigger == RunTrigger.scheduled,
                    AgentRun.id != run_id,
                )
            )
        ) is None


@requires_db
async def test_retrospective_runs_once_then_run_closes(session_factory, company_with_budget):
    """Once the retrospective task exists, the next wind-down closes the run."""
    company_id = company_with_budget
    run_id = await _make_cycle_run(session_factory, company_id, with_retro_marker=True)
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(ctx, company_id=company_id, root_run_id=run_id)

    # No second retrospective; the run closes and the next cycle starts.
    assert len(ctx.enqueued) == 1
    assert ctx.enqueued[0][1] == settings.business_cycle_interval_seconds
    async with session_factory() as db:
        run = await db.get(AgentRun, run_id)
        assert run.status is RunStatus.done


@requires_db
async def test_no_retrospective_when_only_ceo_worked(session_factory, company_with_budget):
    """A cycle where no functional agent completed work skips the retrospective."""
    company_id = company_with_budget
    # Functional task never completed → no worked roles.
    run_id = await _make_cycle_run(
        session_factory, company_id, functional_status=TaskStatus.failed
    )
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(ctx, company_id=company_id, root_run_id=run_id)

    # Straight to closing + next cycle, no retrospective task.
    async with session_factory() as db:
        run = await db.get(AgentRun, run_id)
        assert run.status is RunStatus.done
        assert not await orchestrator._retro_already_ran(db, run_id)


@requires_db
async def test_retrospective_can_be_disabled(session_factory, company_with_budget, monkeypatch):
    company_id = company_with_budget
    monkeypatch.setattr(settings, "business_cycle_retrospective_enabled", False)
    run_id = await _make_cycle_run(session_factory, company_id)
    ctx = _Ctx(session_factory)

    await orchestrator._maybe_continue_cycle(ctx, company_id=company_id, root_run_id=run_id)

    async with session_factory() as db:
        run = await db.get(AgentRun, run_id)
        assert run.status is RunStatus.done  # closed directly, no retro
        assert not await orchestrator._retro_already_ran(db, run_id)


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
