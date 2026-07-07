"""Regression tests for the founder decision / parking flow.

Guards the bug where ``request_decision`` mutated a session-detached ``Task`` and
so never persisted ``waiting_approval`` — leaving the task stuck in ``running``
even though it had escalated. Open-ended escalations are now consolidated into
chat: ``request_decision`` posts a founder DM and parks on a ``ChatWait`` instead
of creating a separate ``DecisionRequest`` (which now only backs structured,
grant-carrying decisions).
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Agent, AgentRun, ChatWait, DecisionRequest, Task
from app.models.enums import (
    AgentRole,
    ChatWaitStatus,
    DecisionKind,
    DecisionStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.backends.native import _consume_approval_grant
from app.runtime.tools import execute_tool
from app.services import chat
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
        # The task must actually be parked in the DB (not silently left running).
        assert row.status is TaskStatus.waiting_approval
        # Open-ended decisions are now founder DMs: a ChatWait marks the wait and
        # the question is posted into the agent↔founder thread (no DecisionRequest).
        wait = await db.scalar(select(ChatWait).where(ChatWait.task_id == task.id))
        assert wait is not None and wait.status is ChatWaitStatus.pending
        channel = await chat.founder_dm(db, company_id=company_id, agent_id=agent.id)
        msgs = await chat.messages(db, channel_id=channel.id)
        assert any("need founder approval" in m.body for m in msgs)
        decisions = await db.scalar(
            select(func.count())
            .select_from(DecisionRequest)
            .where(DecisionRequest.task_id == task.id)
        )
        assert decisions == 0


@requires_db
async def test_submit_plan_is_idempotent_on_rerun(session_factory, company_with_budget):
    """Re-running a still-``running`` CEO task (e.g. after a restart) must not
    create a second plan_approval decision — the founder should see one plan."""
    company_id = company_with_budget
    agent, task = await _make_running_task(session_factory, company_id)

    async def _submit():
        async with session_factory() as db:
            outcome = await execute_tool(
                db,
                object(),
                agent=agent,
                task=task,
                name="submit_plan",
                args={"plan": "## Objective\n- ship the MVP"},
            )
            await db.commit()
            return outcome

    first = await _submit()
    # Second call mirrors the restart re-run: same task, plan already pending.
    second = await _submit()

    assert first.park is True
    assert second.park is True
    async with session_factory() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(DecisionRequest)
            .where(
                DecisionRequest.task_id == task.id,
                DecisionRequest.kind == DecisionKind.plan_approval,
                DecisionRequest.status == DecisionStatus.pending,
            )
        )
        # Exactly one pending plan_approval, not two.
        assert count == 1
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.waiting_approval


@requires_db
async def test_approval_grant_is_one_shot(session_factory, company_with_budget):
    """An approved decision lets the gated action proceed exactly once on resume."""
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
            status=TaskStatus.queued,
        )
        db.add(task)
        await db.flush()
        db.add(
            DecisionRequest(
                company_id=company_id,
                agent_id=agent.id,
                task_id=task.id,
                kind=DecisionKind.spend_approval,
                summary="Approve register_domain",
                payload={"tool": "register_domain", "args": {}},
                status=DecisionStatus.approved,
            )
        )
        await db.commit()
        task_id = task.id

    async with session_factory() as db:
        first = await _consume_approval_grant(db, task_id=task_id, tool="register_domain")
        second = await _consume_approval_grant(db, task_id=task_id, tool="register_domain")
        other = await _consume_approval_grant(db, task_id=task_id, tool="send_email")
        await db.commit()
        # Approved once -> allowed once; never re-escalates the same action, and a
        # different tool is not covered by this grant.
        assert first is True
        assert second is False
        assert other is False
