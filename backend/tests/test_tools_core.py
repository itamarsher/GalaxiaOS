"""Tests for core agent tools that aren't covered by an area-specific suite."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, AgentRun, ChatWait, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    ChatWaitStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.services import chat
from tests.conftest import requires_db


# ── DB-free unit tests ───────────────────────────────────────────────────────
def test_request_user_action_registered():
    spec = next((s for s in TOOL_SPECS if s.name == "request_user_action"), None)
    assert spec is not None
    assert spec.input_schema["type"] == "object"
    assert "action" in spec.input_schema["properties"]
    assert spec.input_schema["required"] == ["action"]


# ── DB-backed integration tests ──────────────────────────────────────────────
async def _agent_and_task(session_factory, company_id, role=AgentRole.growth):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=role, name="A")
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
            goal="do the thing",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()
        return agent, task


@requires_db
async def test_request_user_action_parks_and_asks_founder(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)

    async with session_factory() as db:
        out = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="request_user_action",
            args={"action": "Call the vendor and confirm pricing", "reason": "need the quote"},
        )
        await db.commit()
    assert not out.is_error
    assert out.park is True

    async with session_factory() as db:
        # request_user_action is now a founder DM that waits for the founder's
        # report: a ChatWait parks the task and the ask is posted to the thread.
        wait = await db.scalar(select(ChatWait).where(ChatWait.task_id == task.id))
        assert wait is not None and wait.status is ChatWaitStatus.pending
        channel = await chat.founder_dm(db, company_id=company_id, agent_id=agent.id)
        msgs = await chat.messages(db, channel_id=channel.id)
        assert any("Call the vendor" in m.body for m in msgs)
        # No separate decision row for an open-ended ask.
        decisions = await db.scalar(
            select(DecisionRequest).where(DecisionRequest.task_id == task.id)
        )
        assert decisions is None
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.waiting_approval


@requires_db
async def test_request_user_action_requires_an_action(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)

    async with session_factory() as db:
        out = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="request_user_action",
            args={"action": "   "},
        )
    assert out.is_error
