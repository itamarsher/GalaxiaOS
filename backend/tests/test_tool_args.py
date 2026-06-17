"""Tool dispatch must tolerate malformed model-supplied arguments.

A tool call with a missing/invalid argument (e.g. ``dispatch_task`` without a
``goal``) must surface as a recoverable tool error, not raise and kill the task.
"""

from __future__ import annotations

from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.runtime.tools import execute_tool
from tests.conftest import requires_db


@requires_db
async def test_dispatch_task_missing_goal_is_recoverable(session_factory, company_with_budget):
    company_id = company_with_budget
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

    async with session_factory() as db:
        # "goal" omitted — previously raised KeyError and failed the task.
        outcome = await execute_tool(
            db, object(), agent=agent, task=task, name="dispatch_task", args={"role": "growth"}
        )
        assert outcome.is_error is True
        assert "goal" in outcome.observation

    # Non-dict args must also be tolerated.
    async with session_factory() as db:
        outcome = await execute_tool(
            db, object(), agent=agent, task=task, name="dispatch_task", args=None  # type: ignore[arg-type]
        )
        assert outcome.is_error is True
