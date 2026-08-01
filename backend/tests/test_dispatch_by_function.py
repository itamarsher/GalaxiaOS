"""Dispatching to a business function by its key (not just role).

Several catalog blocks share the ``custom`` role (engineering, customer_service,
billing, …), so a role-only dispatch can't tell them apart — the CEO could never
reach the coding function. ``dispatch_task``/``dispatch_tasks`` accept a
``function`` key (from ``config.function``) that addresses a specific block.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, AgentRun, Task
from app.models.enums import AgentBackendType, AgentRole, RunStatus, RunTrigger, TaskStatus
from app.runtime.tools import execute_tool
from tests.conftest import requires_db


class _Ctx:
    async def enqueue_task(self, _task_id):
        return None


async def _ceo_task(session_factory, company_id):
    async with session_factory() as db:
        ceo = Agent(company_id=company_id, role=AgentRole.ceo, name="CEO")
        db.add(ceo)
        await db.flush()
        run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(company_id=company_id, run_id=run.id, root_run_id=run.id,
                    agent_id=ceo.id, goal="cycle", status=TaskStatus.running)
        db.add(task)
        await db.commit()
        return ceo, task


@requires_db
async def test_dispatch_by_function_reaches_the_right_custom_block(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    async with session_factory() as db:
        # Two custom blocks sharing the `custom` role — role alone can't pick one.
        eng = Agent(company_id=company_id, role=AgentRole.custom, name="Engineering",
                    config={"function": "engineering"}, backend_type=AgentBackendType.external)
        cs = Agent(company_id=company_id, role=AgentRole.custom, name="Customer Service",
                   config={"function": "customer_service"})
        db.add_all([eng, cs])
        await db.commit()
        eng_id, cs_id = eng.id, cs.id
    ceo, task = await _ceo_task(session_factory, company_id)

    async with session_factory() as db:
        outcome = await execute_tool(
            db, _Ctx(), agent=ceo, task=task, name="dispatch_task",
            args={"function": "engineering", "goal": "fix and re-verify the MVP"},
        )
        await db.commit()
    assert outcome.is_error is False
    assert "engineering" in outcome.observation

    # The initiative landed on the engineering block, not the other custom one.
    async with session_factory() as db:
        rows = (await db.scalars(
            select(Task).where(Task.company_id == company_id, Task.goal == "fix and re-verify the MVP")
        )).all()
        assert len(rows) == 1
        assert rows[0].agent_id == eng_id
        assert rows[0].agent_id != cs_id


@requires_db
async def test_dispatch_to_unknown_function_is_a_loud_error(session_factory, company_with_budget):
    company_id = company_with_budget
    ceo, task = await _ceo_task(session_factory, company_id)
    async with session_factory() as db:
        outcome = await execute_tool(
            db, _Ctx(), agent=ceo, task=task, name="dispatch_task",
            args={"function": "engineering", "goal": "build it"},  # no such function provisioned
        )
        await db.commit()
    assert outcome.is_error is True
    assert "engineering" in outcome.observation
    assert "list_team" in outcome.observation
