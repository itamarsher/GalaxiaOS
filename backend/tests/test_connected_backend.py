"""Tests for ConnectedBackend (RFC 0001, migration step 4).

Drives the backend with a fake WorkerClient so the delegation contract is covered
without a real external runtime: it assembles the mandate + initiative, hands them
to the worker, and closes the task through the Business-Function surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.models import Agent, AgentRun, Budget, Company, Mission, Task, User
from app.models.enums import (
    AgentRole,
    BudgetPeriod,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.backends.connected import ConnectedBackend, WorkerReport
from tests.conftest import requires_db

_T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


class _FakeWorker:
    def __init__(self, report=None, raises=None):
        self._report = report
        self._raises = raises
        self.seen = None

    async def execute(self, *, mandate, initiative):
        self.seen = SimpleNamespace(mandate=mandate, initiative=initiative)
        if self._raises is not None:
            raise self._raises
        return self._report


async def _company_agent_task(session_factory, *, task_status=TaskStatus.running):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=10_000))
        db.add(Mission(company_id=company.id, raw_text="Grow the thing.", constraints=[]))
        agent = Agent(company_id=company.id, role=AgentRole.growth, name="Growth Lead",
                      monthly_budget_cents=5_000)
        db.add(agent)
        await db.flush()
        run = AgentRun(company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(company_id=company.id, run_id=run.id, root_run_id=run.id, agent_id=agent.id,
                    goal="publish the launch page", status=task_status, created_at=_T0)
        db.add(task)
        await db.commit()
        # Reload as detached instances the backend can use (it re-fetches via db).
        return company.id, agent, task


@requires_db
async def test_connected_backend_delegates_and_finalizes_done(session_factory):
    company_id, agent, task = await _company_agent_task(session_factory)
    worker = _FakeWorker(WorkerReport(outcome="done", output={"summary": "page is live"}))
    ctx = SimpleNamespace(session_factory=session_factory)

    result = await ConnectedBackend(worker=worker).run(ctx, agent, task)

    assert result["status"] == "done"
    # The worker was handed the mandate + the specific initiative (this task).
    assert worker.seen.mandate.function == "growth"
    assert worker.seen.initiative.goal == "publish the launch page"
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.done
        assert row.output == {"summary": "page is live"}


@requires_db
async def test_connected_backend_needs_decision_parks(session_factory):
    company_id, agent, task = await _company_agent_task(session_factory)
    worker = _FakeWorker(
        WorkerReport(outcome="needs_decision", output={"summary": "Approve the $500 ad test?"})
    )
    ctx = SimpleNamespace(session_factory=session_factory)

    result = await ConnectedBackend(worker=worker).run(ctx, agent, task)

    assert result["status"] == TaskStatus.waiting_approval.value
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.waiting_approval  # parked, not finalized


@requires_db
async def test_connected_backend_fails_gracefully_when_worker_raises(session_factory):
    company_id, agent, task = await _company_agent_task(session_factory)
    worker = _FakeWorker(raises=RuntimeError("gateway timeout"))
    ctx = SimpleNamespace(session_factory=session_factory)

    result = await ConnectedBackend(worker=worker).run(ctx, agent, task)

    assert result["status"] == TaskStatus.failed.value
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.failed
        assert "gateway timeout" in (row.output or {}).get("error", "")


@requires_db
async def test_connected_backend_without_a_worker_fails_clearly(session_factory):
    company_id, agent, task = await _company_agent_task(session_factory)
    ctx = SimpleNamespace(session_factory=session_factory)

    # The registered default has no worker bound — an `external` agent must fail
    # with a clear message rather than silently do nothing.
    result = await ConnectedBackend().run(ctx, agent, task)

    assert result["status"] == TaskStatus.failed.value
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.failed
        assert "no external worker" in (row.output or {}).get("error", "")


def test_external_backend_is_registered():
    # The reserved `external` backend type now resolves to ConnectedBackend.
    from app.runtime.backends import get_backend

    assert isinstance(get_backend("external"), ConnectedBackend)
