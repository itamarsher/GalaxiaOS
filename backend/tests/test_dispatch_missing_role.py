"""Dispatching to a role with no active agent must fail loudly (issue #216).

Before this fix, `dispatch_task`/`dispatch_tasks` silently dropped the initiative
when the requested role had no active agent in the company — `_spawn_child`
returned early with no signal, and the tool still reported success. A CEO
planning against a role the fleet never provisioned (e.g. `research` or
`finance`) would think the work was underway when it never ran.
"""

from __future__ import annotations

from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.runtime.tools import execute_tool
from tests.conftest import requires_db


class _Ctx:
    async def enqueue_task(self, _task_id):
        return None


async def _make_running_task(session_factory, company_id):
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
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return agent, task


@requires_db
async def test_dispatch_task_to_missing_role_is_a_loud_error(session_factory, company_with_budget):
    company_id = company_with_budget  # no non-CEO agents provisioned
    agent, task = await _make_running_task(session_factory, company_id)

    async with session_factory() as db:
        outcome = await execute_tool(
            db, _Ctx(), agent=agent, task=task, name="dispatch_task",
            args={"role": "research", "goal": "identify founder communities"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "research" in outcome.observation
    assert "list_team" in outcome.observation


@requires_db
async def test_dispatch_tasks_reports_missing_roles_but_still_dispatches_the_rest(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    async with session_factory() as db:
        db.add(Agent(company_id=company_id, role=AgentRole.growth, name="Growth"))
        await db.commit()
    agent, task = await _make_running_task(session_factory, company_id)

    async with session_factory() as db:
        outcome = await execute_tool(
            db, _Ctx(), agent=agent, task=task, name="dispatch_tasks",
            args={
                "tasks": [
                    {"role": "growth", "goal": "run a campaign"},
                    {"role": "finance", "goal": "define pricing & packaging"},
                ]
            },
        )
        await db.commit()

    assert outcome.is_error is True
    assert "dispatched 1 sub-tasks" in outcome.observation
    assert "growth" in outcome.observation
    assert "finance" in outcome.observation
    assert "list_team" in outcome.observation
