"""Tests for the QA stabilization fixes (F1, F3, F4, F5, F6).

F2 is a frontend-only change (onboarding recovers from a slow generate POST) and
is covered by the web build, so it has no backend test here.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from sqlalchemy import select

from app.models import (
    Agent,
    AgentRun,
    Budget,
    Company,
    DecisionRequest,
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
    DecisionKind,
    DecisionStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.backends.native import NativeBackend
from app.services import domains as domains_svc
from app.services.budget import BudgetExceeded
from app.services.onboarding import _apply_min_floor
from tests.conftest import requires_db


# ── F4: per-agent budget floor ────────────────────────────────────────────────
def test_apply_min_floor_raises_tiny_slices_and_preserves_ceo():
    from app.config import settings

    floor = settings.launch_agent_min_budget_cents
    # Small weighted slices are lifted to the floor; the CEO's None is untouched.
    out = _apply_min_floor([3, 5, None, 2], total_cents=100_000)
    assert out == [floor, floor, None, floor]


def test_apply_min_floor_scales_down_when_floors_exceed_budget():
    # Floors would over-commit a tiny budget → scaled proportionally to fit it.
    out = _apply_min_floor([3, 5, 2], total_cents=12)
    assert all(c is not None for c in out)
    assert sum(out) <= 12
    assert all(c >= 1 for c in out)


def test_apply_min_floor_noop_without_budget():
    assert _apply_min_floor([None, None], total_cents=None) == [None, None]


# ── F5: domains search degrades gracefully ────────────────────────────────────
async def test_domains_search_returns_empty_without_registrar():
    # Default test config has no registrar → search must return [] (HTTP 200),
    # not raise DomainsError (which the API maps to a 400).
    result = await domains_svc.search(None, company_id=uuid.uuid4(), query="acme.com")
    assert result == []


# ── shared DB helpers ─────────────────────────────────────────────────────────
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


async def _agent_and_task(session_factory, company_id, *, agent_budget):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth",
                      monthly_budget_cents=agent_budget)
        db.add(agent)
        await db.flush()
        run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(company_id=company_id, run_id=run.id, root_run_id=run.id,
                    agent_id=agent.id, goal="g", status=TaskStatus.running)
        db.add(task)
        await db.commit()
        return agent, task


# ── F3: graceful BudgetExceeded on the think step ─────────────────────────────
@requires_db
async def test_extend_agent_budget_tops_up_from_company_pool(session_factory):
    company_id = await _company(session_factory, limit_cents=10_000)
    agent, task = await _agent_and_task(session_factory, company_id, agent_budget=5)
    ctx = SimpleNamespace(session_factory=session_factory)
    backend = NativeBackend()

    ok = await backend._extend_agent_budget(
        ctx, agent, task, BudgetExceeded("agent", requested_cents=50, available_cents=0)
    )
    assert ok is True
    # In-memory copy bumped, and persisted.
    assert agent.monthly_budget_cents > 5
    async with session_factory() as db:
        row = await db.get(Agent, agent.id)
        assert row.monthly_budget_cents == agent.monthly_budget_cents
        assert row.monthly_budget_cents >= 50  # covers the request


@requires_db
async def test_extend_agent_budget_refuses_when_company_is_out(session_factory):
    # Company budget nearly exhausted → can't cover the request → refuse (caller escalates).
    company_id = await _company(session_factory, limit_cents=10_000)
    async with session_factory() as db:
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
        budget.spent_cents = 9_990  # only 10c left
        await db.commit()
    agent, task = await _agent_and_task(session_factory, company_id, agent_budget=5)
    ctx = SimpleNamespace(session_factory=session_factory)
    backend = NativeBackend()

    ok = await backend._extend_agent_budget(
        ctx, agent, task, BudgetExceeded("agent", requested_cents=50, available_cents=0)
    )
    assert ok is False


@requires_db
async def test_park_for_budget_escalates_and_parks_instead_of_failing(session_factory):
    company_id = await _company(session_factory, limit_cents=10_000)
    agent, task = await _agent_and_task(session_factory, company_id, agent_budget=5)
    ctx = SimpleNamespace(session_factory=session_factory)
    backend = NativeBackend()

    await backend._park_for_budget(
        ctx, agent, task, BudgetExceeded("company", requested_cents=50, available_cents=2)
    )
    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.waiting_approval  # parked, NOT failed
        dec = await db.scalar(
            select(DecisionRequest).where(DecisionRequest.task_id == task.id)
        )
        assert dec is not None
        assert dec.kind is DecisionKind.spend_approval
        assert dec.status is DecisionStatus.pending
        assert (dec.payload or {}).get("budget_increase_cents") == 48


# ── F1: key results surfaced on objectives ────────────────────────────────────
@requires_db
async def test_objective_serializes_with_key_results(session_factory):
    from app.schemas import ObjectiveOut

    company_id = await _company(session_factory)
    async with session_factory() as db:
        mission = Mission(company_id=company_id, raw_text="m", constraints=[])
        db.add(mission)
        await db.flush()
        obj = Objective(company_id=company_id, mission_id=mission.id, title="Grow", priority=1)
        db.add(obj)
        await db.flush()
        db.add(KeyResult(company_id=company_id, objective_id=obj.id, metric="subscribers",
                         target_value=100, unit="count"))
        db.add(KeyResult(company_id=company_id, objective_id=obj.id, metric="revenue",
                         target_value=1000, unit="usd"))
        await db.commit()
        obj_id = obj.id

    async with session_factory() as db:
        loaded = await db.scalar(select(Objective).where(Objective.id == obj_id))
        # selectin relationship auto-loads KRs on the async session.
        out = ObjectiveOut.model_validate(loaded)
    assert len(out.key_results) == 2
    assert {kr.metric for kr in out.key_results} == {"subscribers", "revenue"}


# ── F6: copilot context includes objectives ───────────────────────────────────
@requires_db
async def test_copilot_state_includes_objectives(session_factory):
    from app.services import copilot

    company_id = await _company(session_factory)
    async with session_factory() as db:
        mission = Mission(company_id=company_id, raw_text="m", constraints=[])
        db.add(mission)
        await db.flush()
        db.add(Objective(company_id=company_id, mission_id=mission.id,
                         title="Capture early subscribers", priority=1))
        await db.commit()

    async with session_factory() as db:
        # Pass extra_memory=[] to avoid the pgvector-backed memory query (that table
        # is excluded from the test schema).
        state = await copilot._company_state(db, company_id, extra_memory=[])
    assert "Objectives:" in state
    assert "Capture early subscribers" in state
