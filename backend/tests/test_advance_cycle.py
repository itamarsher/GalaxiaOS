"""On-demand "advance cycle" — the game's round trigger.

`runs.start_cycle` mirrors the `run_business_cycle` cron for one company: it kicks
a CEO scheduled run when the company is idle and healthy, and refuses (with a
specific reason) when a cycle is already running, the company isn't active, or the
budget/spend-breaker gate blocks it. These tests pin each branch against a real DB.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, AgentRun, Budget, CircuitBreaker, Company, Membership, Task, User
from app.models.enums import (
    AgentRole,
    BreakerState,
    BreakerType,
    BudgetPeriod,
    CompanyStatus,
    MembershipRole,
    RunTrigger,
    TaskStatus,
)
from app.services import runs
from tests.conftest import requires_db


async def _make_company(
    session_factory,
    *,
    status=CompanyStatus.active,
    limit_cents=50_000,
    spent_cents=0,
    with_ceo=True,
):
    async with session_factory() as db:
        user = User(email="founder@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="Acme", status=status)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=user.id, company_id=company.id, role=MembershipRole.founder))
        db.add(
            Budget(
                company_id=company.id,
                period=BudgetPeriod.monthly,
                limit_cents=limit_cents,
                spent_cents=spent_cents,
            )
        )
        if with_ceo:
            db.add(Agent(company_id=company.id, role=AgentRole.ceo, name="CEO"))
        await db.commit()
        return company.id


@requires_db
async def test_advance_starts_when_idle(session_factory):
    cid = await _make_company(session_factory)
    async with session_factory() as db:
        company = await db.get(Company, cid)
        result = await runs.start_cycle(db, company)
        await db.commit()

    assert result.started is True
    assert result.reason == "started"
    assert result.active is True
    assert result.task_id is not None

    async with session_factory() as db:
        # A scheduled CEO root run + depth-0 queued task now exists.
        run = await db.scalar(
            select(AgentRun).where(
                AgentRun.company_id == cid, AgentRun.trigger == RunTrigger.scheduled
            )
        )
        assert run is not None
        task = await db.get(Task, result.task_id)
        assert task is not None
        assert task.depth == 0
        assert task.status is TaskStatus.queued


@requires_db
async def test_advance_noops_when_cycle_running(session_factory):
    cid = await _make_company(session_factory)
    # Seed a live task so has_active_tasks() is True.
    async with session_factory() as db:
        ceo = await db.scalar(select(Agent).where(Agent.company_id == cid))
        run = AgentRun(company_id=cid, trigger=RunTrigger.scheduled)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        db.add(
            Task(
                company_id=cid, run_id=run.id, root_run_id=run.id,
                agent_id=ceo.id, goal="live", status=TaskStatus.running,
            )
        )
        await db.commit()

    async with session_factory() as db:
        company = await db.get(Company, cid)
        result = await runs.start_cycle(db, company)

    assert result.started is False
    assert result.reason == "already_running"
    assert result.active is True

    async with session_factory() as db:
        # No second scheduled run was created (still exactly one).
        runs_count = len(
            (await db.scalars(select(AgentRun).where(AgentRun.company_id == cid))).all()
        )
        assert runs_count == 1


@requires_db
async def test_advance_blocked_when_not_active(session_factory):
    cid = await _make_company(session_factory, status=CompanyStatus.paused)
    async with session_factory() as db:
        company = await db.get(Company, cid)
        result = await runs.start_cycle(db, company)
    assert result.started is False
    assert result.reason == "not_active"
    assert result.active is False


@requires_db
async def test_advance_blocked_out_of_budget(session_factory):
    # Spend leaves less than business_cycle_min_budget_cents remaining.
    cid = await _make_company(session_factory, limit_cents=1_000, spent_cents=1_000)
    async with session_factory() as db:
        company = await db.get(Company, cid)
        result = await runs.start_cycle(db, company)
    assert result.started is False
    assert result.reason == "insufficient_budget"


@requires_db
async def test_advance_blocked_by_spend_breaker(session_factory):
    cid = await _make_company(session_factory)
    async with session_factory() as db:
        db.add(
            CircuitBreaker(
                company_id=cid, type=BreakerType.spend, state=BreakerState.tripped
            )
        )
        await db.commit()
    async with session_factory() as db:
        company = await db.get(Company, cid)
        result = await runs.start_cycle(db, company)
    assert result.started is False
    assert result.reason == "spend_breaker"


@requires_db
async def test_cycle_status_ready_and_running(session_factory):
    cid = await _make_company(session_factory)
    async with session_factory() as db:
        company = await db.get(Company, cid)
        status_ = await runs.cycle_status(db, company)
    assert status_.active is False
    assert status_.can_start is True
    assert status_.reason == "ready"

    # Now seed a live task and re-check.
    async with session_factory() as db:
        ceo = await db.scalar(select(Agent).where(Agent.company_id == cid))
        run = AgentRun(company_id=cid, trigger=RunTrigger.scheduled)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        db.add(
            Task(
                company_id=cid, run_id=run.id, root_run_id=run.id,
                agent_id=ceo.id, goal="live", status=TaskStatus.running,
            )
        )
        await db.commit()
    async with session_factory() as db:
        company = await db.get(Company, cid)
        status_ = await runs.cycle_status(db, company)
    assert status_.active is True
    assert status_.can_start is False
    assert status_.active_task_count == 1
