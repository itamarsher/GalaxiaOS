"""Restart safety: rebuilding the ephemeral work queue from durable state.

These tests pin :func:`app.jobs.recovery.recover_pending_work`: orphaned
``running`` tasks are reset to ``queued`` and re-enqueued, ``queued`` tasks are
re-enqueued, terminal/awaiting tasks are left alone, and a healthy idle company
gets its continuous loop re-armed (while an out-of-budget one does not). Paused
companies are excluded entirely.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.config import settings
from app.jobs import recovery, scheduled
from app.jobs.recovery import recover_pending_work
from app.models import Agent, AgentRun, Budget, Company, Task
from app.models.enums import (
    AgentRole,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from tests.conftest import requires_db


@pytest.fixture(autouse=True)
def _patch_session_factory(session_factory, monkeypatch):
    """Point the jobs' module-level ``SessionLocal`` at the test database.

    ``recover_pending_work`` and ``_active_company_ids`` use the global
    ``SessionLocal`` (bound to the configured DB); redirect both to the per-test
    schema so recovery runs against the same data the fixtures created.
    """
    monkeypatch.setattr(recovery, "SessionLocal", session_factory)
    monkeypatch.setattr(scheduled, "SessionLocal", session_factory)


class _Enqueue:
    """Records ``(task_id, delay_seconds)`` for each enqueue call."""

    def __init__(self):
        self.calls: list[tuple[uuid.UUID, float]] = []

    async def __call__(self, task_id, *, delay_seconds: float = 0) -> None:
        self.calls.append((task_id, delay_seconds))


async def _add_ceo(db, company_id):
    agent = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
    db.add(agent)
    await db.flush()
    return agent.id


async def _add_task(db, company_id, agent_id, *, status):
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
        agent_id=agent_id,
        goal="g",
        status=status,
    )
    db.add(task)
    await db.flush()
    return task.id


@requires_db
async def test_running_task_is_reset_and_enqueued(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        agent_id = await _add_ceo(db, company_id)
        task_id = await _add_task(db, company_id, agent_id, status=TaskStatus.running)
        await db.commit()

    enqueue = _Enqueue()
    summary = await recover_pending_work(enqueue)

    # Reset to queued and enqueued (delay 0), not re-armed (it has active work).
    async with session_factory() as db:
        task = await db.get(Task, task_id)
        assert task.status is TaskStatus.queued
    assert (task_id, 0) in enqueue.calls
    assert summary["requeued"] == 1
    assert summary["restarted"] == 0


@requires_db
async def test_queued_task_is_enqueued(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        agent_id = await _add_ceo(db, company_id)
        task_id = await _add_task(db, company_id, agent_id, status=TaskStatus.queued)
        await db.commit()

    enqueue = _Enqueue()
    summary = await recover_pending_work(enqueue)

    assert (task_id, 0) in enqueue.calls
    assert summary["requeued"] == 1


@requires_db
async def test_terminal_and_awaiting_tasks_untouched(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        agent_id = await _add_ceo(db, company_id)
        ids = {
            status: await _add_task(db, company_id, agent_id, status=status)
            for status in (
                TaskStatus.waiting_approval,
                TaskStatus.done,
                TaskStatus.failed,
                TaskStatus.blocked,
            )
        }
        await db.commit()

    enqueue = _Enqueue()
    summary = await recover_pending_work(enqueue)

    enqueued_ids = {tid for tid, _ in enqueue.calls}
    assert enqueued_ids.isdisjoint(ids.values())
    assert summary["requeued"] == 0
    # waiting_approval counts as active, so no re-arm either.
    assert summary["restarted"] == 0
    async with session_factory() as db:
        for status, tid in ids.items():
            task = await db.get(Task, tid)
            assert task.status is status


@requires_db
async def test_idle_healthy_company_is_rearmed(session_factory, company_with_budget):
    company_id = company_with_budget  # active, with budget
    async with session_factory() as db:
        await _add_ceo(db, company_id)  # needed for create_scheduled_run
        await db.commit()

    enqueue = _Enqueue()
    summary = await recover_pending_work(enqueue)

    # A fresh scheduled run is created and enqueued with the cycle delay.
    assert summary["restarted"] == 1
    assert len(enqueue.calls) == 1
    assert enqueue.calls[0][1] == settings.business_cycle_interval_seconds
    async with session_factory() as db:
        scheduled = await db.scalar(
            select(AgentRun).where(
                AgentRun.company_id == company_id,
                AgentRun.trigger == RunTrigger.scheduled,
            )
        )
        assert scheduled is not None


@requires_db
async def test_over_budget_company_is_not_rearmed(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        agent_id = await _add_ceo(db, company_id)
        # Spend the whole budget so remaining is below the floor.
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
        budget.spent_cents = budget.limit_cents
        # Existing queued work should still be requeued.
        task_id = await _add_task(db, company_id, agent_id, status=TaskStatus.queued)
        await db.commit()

    enqueue = _Enqueue()
    summary = await recover_pending_work(enqueue)

    assert summary["restarted"] == 0
    assert (task_id, 0) in enqueue.calls
    assert summary["requeued"] == 1
    async with session_factory() as db:
        scheduled = await db.scalar(
            select(AgentRun).where(
                AgentRun.company_id == company_id,
                AgentRun.trigger == RunTrigger.scheduled,
            )
        )
        assert scheduled is None


@requires_db
async def test_paused_company_is_excluded(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        agent_id = await _add_ceo(db, company_id)
        await _add_task(db, company_id, agent_id, status=TaskStatus.running)
        company = await db.get(Company, company_id)
        company.status = CompanyStatus.paused
        await db.commit()

    enqueue = _Enqueue()
    summary = await recover_pending_work(enqueue)

    # Paused company is not active, so recovery skips it entirely.
    assert summary == {"companies": 0, "requeued": 0, "restarted": 0}
    assert enqueue.calls == []
    async with session_factory() as db:
        task = await db.scalar(select(Task).where(Task.company_id == company_id))
        assert task.status is TaskStatus.running  # left untouched
