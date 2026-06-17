"""Budget-request escalation + plan-approval gate (Tasks 1 & 3).

Over-budget requests no longer fail the task — the CEO clears anything within
budget and over-budget asks escalate to the founder, whose approval lifts the
budget ceiling. The CEO must also get the founder's sign-off on the plan before
dispatching any work.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Agent, AgentRun, Budget, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.tools import execute_tool
from app.services import budget as budget_svc
from tests.conftest import requires_db


async def _make_running_task(session_factory, company_id, *, task_input=None):
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
            input=task_input,
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return agent, task


@requires_db
async def test_request_budget_within_budget_is_auto_approved(
    session_factory, company_with_budget
):
    """An ask inside the remaining budget is cleared by the CEO — no founder needed."""
    company_id = company_with_budget  # budget limit is $100.00
    agent, task = await _make_running_task(session_factory, company_id)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="request_budget",
            args={"amount_cents": 2_000, "reason": "a domain"},
        )
        await db.commit()
    assert outcome.park is False
    assert "Approved" in outcome.observation

    async with session_factory() as db:
        pending = await db.scalar(
            select(func.count()).select_from(DecisionRequest)
            .where(DecisionRequest.task_id == task.id)
        )
        row = await db.get(Task, task.id)
    assert pending == 0
    assert row.status is TaskStatus.running  # not parked


@requires_db
async def test_request_budget_over_budget_escalates(session_factory, company_with_budget):
    """An over-budget ask parks the task and raises a spend decision with the shortfall."""
    company_id = company_with_budget  # $100.00 limit, nothing spent
    agent, task = await _make_running_task(session_factory, company_id)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="request_budget",
            args={"amount_cents": 150_00, "reason": "a big ad buy"},
        )
        await db.commit()
    assert outcome.park is True

    async with session_factory() as db:
        decision = await db.scalar(
            select(DecisionRequest).where(DecisionRequest.task_id == task.id)
        )
        row = await db.get(Task, task.id)
    assert decision is not None
    assert decision.kind is DecisionKind.spend_approval
    # Shortfall = 15000 requested - 10000 available.
    assert decision.payload["budget_increase_cents"] == 5_000
    assert row.status is TaskStatus.waiting_approval


@requires_db
async def test_increase_limit_lifts_ceiling(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        await budget_svc.increase_limit(db, company_id=company_id, additional_cents=5_000)
        await db.commit()
    async with session_factory() as db:
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
    assert budget.limit_cents == 15_000


@requires_db
async def test_plan_gate_blocks_dispatch_until_approved(session_factory, company_with_budget):
    """On a launch run dispatch is blocked until the plan is approved."""
    company_id = company_with_budget
    # Also need a growth agent for dispatch to find a target.
    async with session_factory() as db:
        db.add(Agent(company_id=company_id, role=AgentRole.growth, name="Growth"))
        await db.commit()
    agent, task = await _make_running_task(
        session_factory, company_id, task_input={"requires_plan_approval": True}
    )

    # 1) Dispatch before any approval is refused.
    async with session_factory() as db:
        blocked = await execute_tool(
            db, object(), agent=agent, task=task, name="dispatch_task",
            args={"role": "growth", "goal": "do a thing"},
        )
        await db.commit()
    assert blocked.is_error is True
    assert "submit_plan" in blocked.observation

    # 2) submit_plan parks the task and raises a plan_approval decision.
    async with session_factory() as db:
        submitted = await execute_tool(
            db, object(), agent=agent, task=task, name="submit_plan",
            args={"plan": "1. Grow signups via content."},
        )
        await db.commit()
    assert submitted.park is True
    async with session_factory() as db:
        decision = await db.scalar(
            select(DecisionRequest).where(
                DecisionRequest.task_id == task.id,
                DecisionRequest.kind == DecisionKind.plan_approval,
            )
        )
        decision.status = DecisionStatus.approved  # founder approves
        await db.commit()

    # 3) After approval, dispatch goes through.
    class _Ctx:
        async def enqueue_task(self, _task_id):
            return None

    async with session_factory() as db:
        ok = await execute_tool(
            db, _Ctx(), agent=agent, task=task, name="dispatch_task",
            args={"role": "growth", "goal": "do a thing"},
        )
        await db.commit()
    assert ok.is_error is False
    assert "dispatched" in ok.observation
