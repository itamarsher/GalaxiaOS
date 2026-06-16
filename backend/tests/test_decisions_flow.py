"""Regression tests for the founder decision / parking flow.

Guards the bug where ``request_decision`` mutated a session-detached ``Task`` and
so never persisted ``waiting_approval`` — leaving the task stuck in ``running``
even though a pending decision had been raised.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Agent, AgentRun, DecisionRequest, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.runtime.tools import execute_tool
from tests.conftest import requires_db


async def _make_running_task(session_factory, company_id):
    """Create a task left in ``running`` and return it detached (session closed).

    This mirrors how the worker hands a task to the backend: it is loaded and
    committed as ``running`` in one session, which then closes, so the object the
    tool handler later receives is detached from the live DB session.
    """
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
        return agent, task  # detached once the `async with` block exits


@requires_db
async def test_request_decision_parks_detached_task(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _make_running_task(session_factory, company_id)

    # Invoke the tool exactly as NativeBackend._handle_call does: a fresh session,
    # with the detached agent/task objects.
    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="request_decision",
            args={"kind": "strategy", "summary": "need founder approval"},
        )
        await db.commit()
    assert outcome.park is True

    async with session_factory() as db:
        row = await db.get(Task, task.id)
        pending = await db.scalar(
            select(func.count())
            .select_from(DecisionRequest)
            .where(DecisionRequest.task_id == task.id)
        )
        # The task must actually be parked in the DB (not silently left running),
        # and a pending decision must exist for the founder's inbox.
        assert row.status is TaskStatus.waiting_approval
        assert pending == 1
