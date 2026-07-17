"""Tests for the Business-Function surface (RFC 0001, migration step 1).

The surface is a thin orchestration over existing services, so these tests assert
it assembles the mandate from real business state, offers the right initiative, and
reports results through the shared finalize path — without changing any behaviour.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import (
    Agent,
    AgentRun,
    Budget,
    Company,
    KeyResult,
    Mission,
    Objective,
    Task,
    User,
)
from app.models.enums import (
    AgentRole,
    BudgetPeriod,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.services import business_function as bf
from tests.conftest import requires_db

_T0 = datetime(2026, 7, 1, tzinfo=timezone.utc)


async def _company(session_factory, *, limit_cents=10_000):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=limit_cents))
        await db.commit()
        return company.id


async def _agent(db, company_id, *, role=AgentRole.growth, name="Growth Lead", budget=5_000):
    agent = Agent(company_id=company_id, role=role, name=name, monthly_budget_cents=budget)
    db.add(agent)
    await db.flush()
    return agent


async def _run(db, company_id):
    run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    return run


async def _task(db, company_id, run, agent_id, *, status, goal, created_at):
    task = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent_id,
        goal=goal,
        status=status,
        created_at=created_at,
    )
    db.add(task)
    await db.flush()
    return task


# ── get_mandate ───────────────────────────────────────────────────────────────
@requires_db
async def test_get_mandate_assembles_from_business_state(session_factory):
    company_id = await _company(session_factory, limit_cents=10_000)
    async with session_factory() as db:
        mission = Mission(
            company_id=company_id,
            raw_text="Make owning a business a right.",
            constraints=["No paid ads", "English only"],
        )
        db.add(mission)
        await db.flush()
        obj = Objective(company_id=company_id, mission_id=mission.id, title="Capture demand", priority=1)
        db.add(obj)
        await db.flush()
        db.add(KeyResult(company_id=company_id, objective_id=obj.id, metric="waitlist signups",
                         target_value=500, unit="count"))
        agent = await _agent(db, company_id, role=AgentRole.growth, name="Growth Lead", budget=5_000)
        await db.commit()
        agent_id = agent.id

    async with session_factory() as db:
        mandate = await bf.get_mandate(db, company_id=company_id, agent_id=agent_id)

    assert mandate.function == "growth"
    assert mandate.function_title == "Growth Lead"
    assert "right" in mandate.mission
    assert "Capture demand" in mandate.objectives
    assert mandate.constraints == ["No paid ads", "English only"]
    # Budget envelope: the function's own slice + the company pool, both fresh.
    assert mandate.budget.function_limit_cents == 5_000
    assert mandate.budget.function_remaining_cents == 5_000  # nothing spent yet
    assert mandate.budget.company_limit_cents == 10_000
    assert mandate.budget.company_remaining_cents == 10_000


@requires_db
async def test_get_mandate_unknown_agent_raises(session_factory):
    company_id = await _company(session_factory)
    async with session_factory() as db:
        with pytest.raises(ValueError):
            await bf.get_mandate(db, company_id=company_id, agent_id=uuid.uuid4())


# ── get_next_initiative ────────────────────────────────────────────────────────
@requires_db
async def test_get_next_initiative_prefers_running_then_oldest(session_factory):
    company_id = await _company(session_factory)
    async with session_factory() as db:
        agent = await _agent(db, company_id)
        other = await _agent(db, company_id, role=AgentRole.product, name="Product Lead")
        run = await _run(db, company_id)
        # oldest queued should win among queued tasks…
        old = await _task(db, company_id, run, agent.id, status=TaskStatus.queued,
                          goal="old queued", created_at=_T0)
        await _task(db, company_id, run, agent.id, status=TaskStatus.queued,
                    goal="new queued", created_at=_T0 + timedelta(hours=1))
        # …a done task is ignored, and another function's task is never offered.
        await _task(db, company_id, run, agent.id, status=TaskStatus.done,
                    goal="finished", created_at=_T0 - timedelta(hours=1))
        await _task(db, company_id, run, other.id, status=TaskStatus.queued,
                    goal="not mine", created_at=_T0 - timedelta(hours=2))
        await db.commit()
        agent_id, old_id = agent.id, old.id

    async with session_factory() as db:
        nxt = await bf.get_next_initiative(db, company_id=company_id, agent_id=agent_id)
    assert nxt is not None and nxt.id == old_id and nxt.goal == "old queued"
    assert nxt.function == "growth"

    # A running task outranks any queued one, even a newer one.
    async with session_factory() as db:
        newer = await db.scalar(
            select(Task).where(Task.agent_id == agent_id, Task.goal == "new queued")
        )
        newer.status = TaskStatus.running
        await db.commit()
    async with session_factory() as db:
        nxt = await bf.get_next_initiative(db, company_id=company_id, agent_id=agent_id)
    assert nxt is not None and nxt.goal == "new queued" and nxt.status == "running"


@requires_db
async def test_get_next_initiative_none_when_idle(session_factory):
    company_id = await _company(session_factory)
    async with session_factory() as db:
        agent = await _agent(db, company_id)
        run = await _run(db, company_id)
        await _task(db, company_id, run, agent.id, status=TaskStatus.done,
                    goal="all done", created_at=_T0)
        await db.commit()
        agent_id = agent.id
    async with session_factory() as db:
        assert await bf.get_next_initiative(db, company_id=company_id, agent_id=agent_id) is None


# ── report_result ──────────────────────────────────────────────────────────────
@requires_db
async def test_report_result_finalizes_and_maps_outcome(session_factory):
    company_id = await _company(session_factory)
    async with session_factory() as db:
        agent = await _agent(db, company_id)
        run = await _run(db, company_id)
        task = await _task(db, company_id, run, agent.id, status=TaskStatus.running,
                           goal="do the thing", created_at=_T0)
        await db.commit()
        task_id = task.id

    async with session_factory() as db:
        await bf.report_result(
            db, company_id=company_id, task_id=task_id,
            outcome="done", output={"summary": "shipped it"},
        )
        await db.commit()

    async with session_factory() as db:
        row = await db.get(Task, task_id)
        assert row.status is TaskStatus.done
        assert row.output == {"summary": "shipped it"}


@requires_db
async def test_report_result_rejects_bad_outcome_and_foreign_task(session_factory):
    company_id = await _company(session_factory)
    other_company = await _company(session_factory)
    async with session_factory() as db:
        agent = await _agent(db, company_id)
        run = await _run(db, company_id)
        task = await _task(db, company_id, run, agent.id, status=TaskStatus.running,
                           goal="g", created_at=_T0)
        await db.commit()
        task_id = task.id

    async with session_factory() as db:
        with pytest.raises(ValueError):
            await bf.report_result(db, company_id=company_id, task_id=task_id,
                                   outcome="banana", output={})
        # A task that belongs to another company must not be closeable here.
        with pytest.raises(ValueError):
            await bf.report_result(db, company_id=other_company, task_id=task_id,
                                   outcome="done", output={})
