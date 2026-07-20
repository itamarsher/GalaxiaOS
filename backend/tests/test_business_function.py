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


async def _agent(db, company_id, *, role=AgentRole.growth, name="Growth Lead", budget=5_000,
                 access_labels=None):
    agent = Agent(company_id=company_id, role=role, name=name, monthly_budget_cents=budget,
                  access_labels=access_labels)
    db.add(agent)
    await db.flush()
    return agent


@requires_db
async def test_mandate_redacts_financial_metrics_for_uncleared_external_worker(session_factory):
    """redact_for_access withholds money-denominated signals from a worker lacking the
    financial label; native (unredacted) and financial-cleared workers get them."""
    from app.models import MetricSignal
    from app.models.enums import MetricSource

    company_id = await _company(session_factory)
    async with session_factory() as db:
        db.add(MetricSignal(company_id=company_id, name="revenue", value=1234.0, unit="USD",
                            source=MetricSource.agent))
        db.add(MetricSignal(company_id=company_id, name="signups", value=42.0, unit="users",
                            source=MetricSource.agent))
        uncleared = await _agent(db, company_id, access_labels=[])
        cleared = await _agent(db, company_id, name="Fin", access_labels=["financial"])
        await db.commit()
        uncleared_id, cleared_id = uncleared.id, cleared.id

    async with session_factory() as db:
        # Native / unredacted → full metrics.
        full = await bf.get_mandate(db, company_id=company_id, agent_id=uncleared_id)
        assert "revenue" in full.metrics and "signups" in full.metrics
        # External + uncleared → money signal withheld, ops signal kept.
        red = await bf.get_mandate(db, company_id=company_id, agent_id=uncleared_id,
                                   redact_for_access=True)
        assert "revenue" not in red.metrics and "signups" in red.metrics
        # External + financial-cleared → money signal kept.
        ok = await bf.get_mandate(db, company_id=company_id, agent_id=cleared_id,
                                  redact_for_access=True)
        assert "revenue" in ok.metrics


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


# ── claim / lease (async-first lifecycle) ──────────────────────────────────────
@requires_db
async def test_claim_initiative_is_atomic_single_winner(session_factory):
    company_id = await _company(session_factory)
    async with session_factory() as db:
        agent = await _agent(db, company_id)
        run = await _run(db, company_id)
        task = await _task(db, company_id, run, agent.id, status=TaskStatus.queued,
                           goal="offered work", created_at=_T0)
        await db.commit()
        agent_id, task_id = agent.id, task.id

    # First claim wins and flips the task to running with a lease.
    async with session_factory() as db:
        won = await bf.claim_initiative(db, company_id=company_id, agent_id=agent_id, task_id=task_id)
        await db.commit()
    assert won is not None and won.status == "running"
    async with session_factory() as db:
        row = await db.get(Task, task_id)
        assert row.status is TaskStatus.running and row.lease_expires_at is not None

    # A second claim on the now-running task finds nothing to take.
    async with session_factory() as db:
        again = await bf.claim_initiative(db, company_id=company_id, agent_id=agent_id, task_id=task_id)
        await db.commit()
    assert again is None


@requires_db
async def test_release_expired_claims_reassigns_only_leased_and_expired(session_factory):
    from datetime import timedelta

    company_id = await _company(session_factory)
    async with session_factory() as db:
        agent = await _agent(db, company_id)
        run = await _run(db, company_id)
        # A pull-claimed initiative with a short lease…
        leased = await _task(db, company_id, run, agent.id, status=TaskStatus.queued,
                             goal="leased", created_at=_T0)
        # …and a push-run (native) task with NO lease — must never be reclaimed.
        unleased = await _task(db, company_id, run, agent.id, status=TaskStatus.running,
                               goal="native running", created_at=_T0)
        await db.commit()
        leased_id, unleased_id = leased.id, unleased.id
        agent_id = agent.id

    async with session_factory() as db:
        await bf.claim_initiative(db, company_id=company_id, agent_id=agent_id,
                                  task_id=leased_id, lease_seconds=60)
        await db.commit()

    # Reclaim as-of a moment past the lease: the leased one returns to queued; the
    # unleased native task is untouched.
    async with session_factory() as db:
        n = await bf.release_expired_claims(
            db, company_id=company_id, now=datetime.now(timezone.utc) + timedelta(hours=1)
        )
        await db.commit()
    assert n == 1
    async with session_factory() as db:
        assert (await db.get(Task, leased_id)).status is TaskStatus.queued
        assert (await db.get(Task, leased_id)).lease_expires_at is None
        assert (await db.get(Task, unleased_id)).status is TaskStatus.running


@requires_db
async def test_report_result_clears_the_lease(session_factory):
    company_id = await _company(session_factory)
    async with session_factory() as db:
        agent = await _agent(db, company_id)
        run = await _run(db, company_id)
        task = await _task(db, company_id, run, agent.id, status=TaskStatus.queued,
                           goal="claim then finish", created_at=_T0)
        await db.commit()
        agent_id, task_id = agent.id, task.id
    async with session_factory() as db:
        await bf.claim_initiative(db, company_id=company_id, agent_id=agent_id, task_id=task_id)
        await bf.report_result(db, company_id=company_id, task_id=task_id,
                               outcome="done", output={"summary": "ok"})
        await db.commit()
    async with session_factory() as db:
        row = await db.get(Task, task_id)
        assert row.status is TaskStatus.done and row.lease_expires_at is None


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
async def test_report_result_needs_decision_parks_and_escalates(session_factory):
    from app.models import ChatMessage

    company_id = await _company(session_factory)
    async with session_factory() as db:
        agent = await _agent(db, company_id)
        run = await _run(db, company_id)
        task = await _task(db, company_id, run, agent.id, status=TaskStatus.running,
                           goal="pick a pricing tier", created_at=_T0)
        await db.commit()
        task_id = task.id

    async with session_factory() as db:
        await bf.report_result(
            db, company_id=company_id, task_id=task_id, outcome="needs_decision",
            output={"summary": "Do we price the hosted tier at $29 or $49?"},
        )
        await db.commit()

    async with session_factory() as db:
        row = await db.get(Task, task_id)
        # Parked, NOT finalized — so it can resume after the founder replies.
        assert row.status is TaskStatus.waiting_approval
        # The ask was escalated to the founder's DM.
        msg = await db.scalar(
            select(ChatMessage).where(ChatMessage.company_id == company_id)
        )
        assert msg is not None and "hosted tier" in msg.body


@requires_db
async def test_report_result_needs_decision_requires_a_summary(session_factory):
    company_id = await _company(session_factory)
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
                                   outcome="needs_decision", output={})


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
