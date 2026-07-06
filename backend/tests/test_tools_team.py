"""Tests for the CEO team-management tools (hire / pause / resume / reallocate)."""

from __future__ import annotations

from app.models import Agent, AgentRun, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    AgentSource,
    AgentStatus,
    DecisionKind,
    DecisionStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.runtime.tools.team import HANDLERS, SPECS, _reallocate_hint, _require_ceo, _usd
from app.services import budget as budget_svc
from tests.conftest import requires_db

TEAM_TOOL_NAMES = (
    "list_team",
    "hire_agent",
    "pause_agent",
    "resume_agent",
    "set_agent_budget",
    "get_company_playbook",
    "update_company_playbook",
    "set_agent_directive",
)


# ── DB-free unit tests ───────────────────────────────────────────────────────
def test_team_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in TEAM_TOOL_NAMES:
        assert expected in names


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS} == set(TEAM_TOOL_NAMES)


def test_specs_have_object_schema_with_properties():
    for spec in SPECS:
        assert spec.input_schema["type"] == "object"
        assert "properties" in spec.input_schema


def test_hire_role_enum_excludes_ceo():
    hire = next(s for s in SPECS if s.name == "hire_agent")
    assert "ceo" not in hire.input_schema["properties"]["role"]["enum"]
    assert "growth" in hire.input_schema["properties"]["role"]["enum"]


def test_usd_formats_cents():
    assert _usd(0) == "$0.00"
    assert _usd(4000) == "$40.00"
    assert _usd(123456) == "$1,234.56"


def test_require_ceo_refuses_non_ceo():
    growth = Agent(role=AgentRole.growth, name="G")
    refusal = _require_ceo(growth)
    assert refusal is not None and refusal.is_error
    assert _require_ceo(Agent(role=AgentRole.ceo, name="CEO")) is None


def test_reallocate_hint_mentions_levers():
    hint = _reallocate_hint(0)
    assert "set_agent_budget" in hint and "pause_agent" in hint


# ── DB-backed integration tests ──────────────────────────────────────────────
async def _grant_hire(db, task):
    """Seed an approved hire decision so the next ``hire_agent`` call proceeds.

    Hiring now requires the founder's sign-off; an approved decision acts as a
    one-shot grant (see ``consume_approval_grant``), mirroring how the app
    re-queues the task after the founder approves.
    """
    db.add(
        DecisionRequest(
            company_id=task.company_id,
            task_id=task.id,
            kind=DecisionKind.hire_approval,
            summary="grant",
            payload={"tool": "hire_agent"},
            status=DecisionStatus.approved,
        )
    )
    await db.flush()


async def _hire(db, ceo, task, **args):
    """Hire with founder approval already granted (the common case in tests)."""
    await _grant_hire(db, task)
    return await execute_tool(
        db, object(), agent=ceo, task=task, name="hire_agent", args=args
    )


async def _ceo_and_task(session_factory, company_id):
    """Persist a CEO agent + a running root task, returning fresh instances."""
    async with session_factory() as db:
        ceo = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
        db.add(ceo)
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=ceo.id,
            goal="run the business",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return ceo, task


@requires_db
async def test_hire_agent_allocates_from_pool(session_factory, company_with_budget):
    company_id = company_with_budget  # limit = $100.00
    ceo, task = await _ceo_and_task(session_factory, company_id)

    async with session_factory() as db:
        out = await _hire(db, ceo, task, role="growth", name="Ada", monthly_budget_cents=4000)
        await db.commit()
    assert not out.is_error
    assert "Hired Ada" in out.observation

    async with session_factory() as db:
        hired = await db.scalar(select_agent_by_name(db, company_id, "Ada"))
        assert hired is not None
        assert hired.role is AgentRole.growth
        assert hired.source is AgentSource.hired
        assert hired.monthly_budget_cents == 4000
        assert hired.reports_to_agent_id == ceo.id
        overview = await budget_svc.allocation_overview(db, company_id)
        assert overview["pool_cents"] == 6000  # 10000 - 4000


@requires_db
async def test_hire_agent_requests_founder_approval(session_factory, company_with_budget):
    """Without a standing approval, hiring parks the task and asks the founder."""
    company_id = company_with_budget
    ceo, task = await _ceo_and_task(session_factory, company_id)

    async with session_factory() as db:
        out = await execute_tool(
            db, object(), agent=ceo, task=task, name="hire_agent",
            args={"role": "growth", "name": "Ada", "monthly_budget_cents": 4000},
        )
        await db.commit()
    assert not out.is_error
    assert out.park is True
    assert "approval" in out.observation.lower()

    async with session_factory() as db:
        # No agent was created yet — only a pending hire decision exists.
        assert await db.scalar(select_agent_by_name(db, company_id, "Ada")) is None
        from sqlalchemy import select

        decision = await db.scalar(
            select(DecisionRequest).where(DecisionRequest.task_id == task.id)
        )
        assert decision is not None
        assert decision.kind is DecisionKind.hire_approval
        assert decision.status is DecisionStatus.pending
        assert (decision.payload or {}).get("tool") == "hire_agent"


@requires_db
async def test_hire_over_pool_is_refused_with_reallocation_prompt(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    ceo, task = await _ceo_and_task(session_factory, company_id)

    async with session_factory() as db:
        out = await _hire(
            db, ceo, task, role="research", name="Too Big", monthly_budget_cents=20000
        )
    assert out.is_error
    # The CEO is prompted to reallocate or pause, not just told "no".
    assert "set_agent_budget" in out.observation and "pause_agent" in out.observation


@requires_db
async def test_pause_returns_unspent_budget_then_resume_reclaims(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    ceo, task = await _ceo_and_task(session_factory, company_id)

    # Hire two agents that together earmark the whole pool.
    async with session_factory() as db:
        for name, cents in (("Ada", 6000), ("Bo", 4000)):
            await _hire(db, ceo, task, role="growth", name=name, monthly_budget_cents=cents)
        await db.commit()
        overview = await budget_svc.allocation_overview(db, company_id)
        assert overview["pool_cents"] == 0  # fully allocated

    # Pausing Bo returns its $40 to the pool.
    async with session_factory() as db:
        out = await execute_tool(
            db, object(), agent=ceo, task=task, name="pause_agent", args={"name": "Bo"},
        )
        await db.commit()
        assert not out.is_error and "Returned $40.00" in out.observation
        bo = await db.scalar(select_agent_by_name(db, company_id, "Bo"))
        assert bo.status is AgentStatus.paused
        overview = await budget_svc.allocation_overview(db, company_id)
        assert overview["pool_cents"] == 4000

    # Resuming Bo re-claims it (fits, since nothing else took the pool).
    async with session_factory() as db:
        out = await execute_tool(
            db, object(), agent=ceo, task=task, name="resume_agent", args={"name": "Bo"},
        )
        await db.commit()
        assert not out.is_error
        bo = await db.scalar(select_agent_by_name(db, company_id, "Bo"))
        assert bo.status is AgentStatus.active


@requires_db
async def test_resume_refused_when_pool_cannot_cover(session_factory, company_with_budget):
    company_id = company_with_budget
    ceo, task = await _ceo_and_task(session_factory, company_id)

    async with session_factory() as db:
        await _hire(db, ceo, task, role="growth", name="Ada", monthly_budget_cents=4000)
        await db.commit()

    # Pause Ada (pool -> 10000), then hire someone that consumes the whole pool.
    async with session_factory() as db:
        await execute_tool(
            db, object(), agent=ceo, task=task, name="pause_agent", args={"name": "Ada"},
        )
        await _hire(db, ceo, task, role="research", name="Cy", monthly_budget_cents=10000)
        await db.commit()

    # Now resuming Ada can't re-claim its $40 — pool is empty.
    async with session_factory() as db:
        out = await execute_tool(
            db, object(), agent=ceo, task=task, name="resume_agent", args={"name": "Ada"},
        )
        assert out.is_error
        assert "Can't resume Ada" in out.observation


@requires_db
async def test_set_agent_budget_reallocates(session_factory, company_with_budget):
    company_id = company_with_budget
    ceo, task = await _ceo_and_task(session_factory, company_id)

    async with session_factory() as db:
        await _hire(db, ceo, task, role="growth", name="Ada", monthly_budget_cents=8000)
        await db.commit()

    # Lower Ada's cap, freeing budget back to the pool.
    async with session_factory() as db:
        out = await execute_tool(
            db, object(), agent=ceo, task=task, name="set_agent_budget",
            args={"name": "Ada", "monthly_budget_cents": 3000},
        )
        await db.commit()
        assert not out.is_error
        overview = await budget_svc.allocation_overview(db, company_id)
        assert overview["pool_cents"] == 7000  # 10000 - 3000


@requires_db
async def test_non_ceo_cannot_manage_team(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        growth = Agent(company_id=company_id, role=AgentRole.growth, name="G")
        db.add(growth)
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=growth.id, goal="g", status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()

    async with session_factory() as db:
        out = await execute_tool(
            db, object(), agent=growth, task=task, name="hire_agent",
            args={"role": "research", "name": "X", "monthly_budget_cents": 1000},
        )
    assert out.is_error and "Only the CEO" in out.observation


def select_agent_by_name(db, company_id, name):
    from sqlalchemy import select

    return select(Agent).where(Agent.company_id == company_id, Agent.name == name)
