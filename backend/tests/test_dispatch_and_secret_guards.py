"""Two guards on the agent core tools:

* G2 — ``request_user_action`` must refuse credential-shaped asks and point the agent
  at the encrypted ``request_secret`` path (a chat reply would leak the value).
* G4 — ``dispatch_task`` must not spawn a second initiative that duplicates one already
  in flight (same goal, or same objective + same role), so the CEO re-planning every
  cycle can't double up work (two tasks publishing the same landing page).
"""

from __future__ import annotations

from app.models import Agent, AgentRun, Mission, Objective, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.runtime.tools import execute_tool
from tests.conftest import requires_db


class _Ctx:
    async def enqueue_task(self, _task_id):
        return None


async def _ceo_task(session_factory, company_id, *, objective_id=None):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
        db.add(agent)
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
            agent_id=agent.id,
            goal="dispatch the next initiatives",
            status=TaskStatus.running,
            objective_id=objective_id,
        )
        db.add(task)
        await db.commit()
        return agent, task


@requires_db
async def test_request_user_action_redirects_credential_asks(session_factory, company_with_budget):
    agent, task = await _ceo_task(session_factory, company_with_budget)
    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _Ctx(),
            agent=agent,
            task=task,
            name="request_user_action",
            args={
                "action": "Please provide your Cloudflare API token so I can publish the page",
                "reason": "needed for hosting",
            },
        )
    assert outcome.is_error is True
    assert "request_secret" in outcome.observation


@requires_db
async def test_dispatch_skips_a_duplicate_same_goal(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        db.add(Agent(company_id=company_id, role=AgentRole.growth, name="Growth"))
        await db.commit()
    agent, task = await _ceo_task(session_factory, company_id)

    async with session_factory() as db:
        first = await execute_tool(
            db, _Ctx(), agent=agent, task=task, name="dispatch_task",
            args={"role": "growth", "goal": "publish the landing page"},
        )
        await db.commit()
    assert first.is_error is False
    assert "dispatched" in first.observation

    async with session_factory() as db:
        # Different casing/whitespace, same normalized goal → deduped, not re-dispatched.
        second = await execute_tool(
            db, _Ctx(), agent=agent, task=task, name="dispatch_task",
            args={"role": "growth", "goal": "Publish the   Landing Page"},
        )
        await db.commit()
    assert second.is_error is False
    assert "already in flight" in second.observation

    async with session_factory() as db:
        from sqlalchemy import func, select

        n = await db.scalar(
            select(func.count(Task.id)).where(
                Task.company_id == company_id, Task.parent_task_id == task.id
            )
        )
    assert n == 1  # only the first initiative was spawned


@requires_db
async def test_dispatch_skips_same_objective_same_role_even_with_different_goal(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    async with session_factory() as db:
        db.add(Agent(company_id=company_id, role=AgentRole.growth, name="Growth"))
        mission = Mission(company_id=company_id, raw_text="grow", constraints=[])
        db.add(mission)
        await db.flush()
        objective = Objective(company_id=company_id, mission_id=mission.id, title="Launch")
        db.add(objective)
        await db.flush()
        oid = objective.id
        await db.commit()
    agent, task = await _ceo_task(session_factory, company_id, objective_id=oid)

    async with session_factory() as db:
        first = await execute_tool(
            db, _Ctx(), agent=agent, task=task, name="dispatch_task",
            args={"role": "growth", "goal": "write and publish the landing page copy"},
        )
        await db.commit()
    assert "dispatched" in first.observation

    async with session_factory() as db:
        # A different goal, but the same objective handled by the same role → deduped.
        second = await execute_tool(
            db, _Ctx(), agent=agent, task=task, name="dispatch_task",
            args={"role": "growth", "goal": "ship the live waitlist page to production"},
        )
        await db.commit()
    assert "already in flight" in second.observation
