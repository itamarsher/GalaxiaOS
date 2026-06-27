"""Tests for the chat collaboration layer and the reply-wait mechanic.

Covers the agent tools (open a channel, post, DM), the parking flow when an agent
waits for a reply (mirroring the founder-decision parking), and the resume path
where a teammate's or the founder's reply wakes the parked task and is delivered
to the agent without re-posting the original message.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import (
    Agent,
    AgentRun,
    ChatChannel,
    ChatMessage,
    ChatWait,
    DecisionRequest,
    Task,
)
from app.models.enums import (
    AgentRole,
    ChatChannelKind,
    ChatWaitStatus,
    DecisionKind,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.services import chat
from tests.conftest import requires_db


class FakeCtx:
    """Minimal RuntimeContext stand-in that records re-enqueued task ids."""

    def __init__(self):
        self.enqueued: list = []

    async def enqueue_task(self, task_id, *, delay_seconds: float = 0):
        self.enqueued.append(task_id)


# ── DB-free unit tests ───────────────────────────────────────────────────────
def test_chat_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in (
        "list_chat_channels",
        "start_chat_channel",
        "read_chat_channel",
        "send_chat_message",
        "message_teammate",
    ):
        assert expected in names


def test_send_chat_message_schema():
    spec = next(s for s in TOOL_SPECS if s.name == "send_chat_message")
    props = spec.input_schema["properties"]
    assert "wait_for_reply" in props
    assert spec.input_schema["required"] == ["channel", "message"]


# ── DB-backed helpers ─────────────────────────────────────────────────────────
async def _agent_and_task(session_factory, company_id, role=AgentRole.growth, name="A"):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=role, name=name)
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


# ── DB-backed integration tests ──────────────────────────────────────────────
@requires_db
async def test_start_channel_and_post(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)

    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="start_chat_channel",
            args={"name": "q3-launch", "purpose": "Coordinate the launch"},
        )
        await db.commit()
    assert not out.is_error
    assert "q3-launch" in out.observation

    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="send_chat_message",
            args={"channel": "q3-launch", "message": "Kicking this off."},
        )
        await db.commit()
    assert not out.is_error
    assert out.park is False

    async with session_factory() as db:
        channel = await chat.find_channel_by_name(db, company_id=company_id, name="q3-launch")
        assert channel is not None
        msgs = await chat.messages(db, channel_id=channel.id)
        assert [m.body for m in msgs] == ["Kicking this off."]
        # Creator and founder are participants.
        parts = await chat.participants(db, channel.id)
        agent_ids = {p.agent_id for p in parts}
        assert agent.id in agent_ids and None in agent_ids


@requires_db
async def test_send_with_wait_parks_task(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)

    async with session_factory() as db:
        await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=agent.id
        )
        await db.commit()

    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="send_chat_message",
            args={
                "channel": "war-room",
                "message": "Need input — waiting.",
                "wait_for_reply": True,
            },
        )
        await db.commit()
    assert out.park is True

    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.waiting_approval
        wait = await db.scalar(select(ChatWait).where(ChatWait.task_id == task.id))
        assert wait is not None and wait.status is ChatWaitStatus.pending
        # The message was posted exactly once.
        count = await db.scalar(
            select(func.count(ChatMessage.id)).where(ChatMessage.channel_id == wait.channel_id)
        )
        assert count == 1


@requires_db
async def test_founder_reply_wakes_waiting_agent(session_factory, company_with_budget):
    """A founder post satisfies the wait, re-queues the task, and is delivered on resume."""
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)

    async with session_factory() as db:
        await chat.create_channel(
            db, company_id=company_id, name="ask-founder", created_by_agent_id=agent.id
        )
        await db.commit()

    # Agent posts and waits.
    async with session_factory() as db:
        await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="send_chat_message",
            args={
                "channel": "ask-founder",
                "message": "Approve approach A or B?",
                "wait_for_reply": True,
            },
        )
        await db.commit()

    # Founder replies (the app.api.chat path: post as sender_agent_id=None).
    async with session_factory() as db:
        channel = await chat.find_channel_by_name(db, company_id=company_id, name="ask-founder")
        _, woken = await chat.post_message(
            db,
            company_id=company_id,
            channel_id=channel.id,
            sender_agent_id=None,
            body="Go with B.",
        )
        await db.commit()
    assert task.id in woken

    async with session_factory() as db:
        row = await db.get(Task, task.id)
        assert row.status is TaskStatus.queued  # re-queued for resume
        wait = await db.scalar(select(ChatWait).where(ChatWait.task_id == task.id))
        assert wait.status is ChatWaitStatus.satisfied

    # Resume: the agent re-issues the same send; it must DELIVER the reply, not re-post.
    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="send_chat_message",
            args={
                "channel": "ask-founder",
                "message": "Approve approach A or B?",
                "wait_for_reply": True,
            },
        )
        await db.commit()
    assert out.park is False
    assert "Go with B." in out.observation

    async with session_factory() as db:
        channel = await chat.find_channel_by_name(db, company_id=company_id, name="ask-founder")
        # Still exactly one agent message — the resume did not double-post.
        count = await db.scalar(
            select(func.count(ChatMessage.id)).where(
                ChatMessage.channel_id == channel.id,
                ChatMessage.sender_agent_id == agent.id,
            )
        )
        assert count == 1
        wait = await db.scalar(select(ChatWait).where(ChatWait.task_id == task.id))
        assert wait.status is ChatWaitStatus.consumed


@requires_db
async def test_agent_reply_wakes_other_agent(session_factory, company_with_budget):
    """An agent posting wakes another agent waiting in the channel, but not itself."""
    company_id = company_with_budget
    waiter, waiter_task = await _agent_and_task(
        session_factory, company_id, role=AgentRole.growth, name="Grow"
    )
    other, other_task = await _agent_and_task(
        session_factory, company_id, role=AgentRole.research, name="Res"
    )

    async with session_factory() as db:
        await chat.create_channel(
            db, company_id=company_id, name="collab", created_by_agent_id=waiter.id
        )
        await db.commit()

    async with session_factory() as db:
        await execute_tool(
            db,
            FakeCtx(),
            agent=waiter,
            task=waiter_task,
            name="send_chat_message",
            args={
                "channel": "collab",
                "message": "Research, what's the TAM?",
                "wait_for_reply": True,
            },
        )
        await db.commit()

    # The other agent answers via the tool; this should wake the waiter.
    ctx = FakeCtx()
    async with session_factory() as db:
        out = await execute_tool(
            db,
            ctx,
            agent=other,
            task=other_task,
            name="send_chat_message",
            args={"channel": "collab", "message": "~$2B."},
        )
        await db.commit()
    assert not out.is_error
    assert waiter_task.id in ctx.enqueued

    async with session_factory() as db:
        row = await db.get(Task, waiter_task.id)
        assert row.status is TaskStatus.queued


@requires_db
async def test_message_teammate_creates_direct_channel(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id)

    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="message_teammate",
            args={"to": "founder", "message": "Quick question for you."},
        )
        await db.commit()
    assert not out.is_error

    async with session_factory() as db:
        directs = (
            await db.scalars(
                select(ChatChannel).where(
                    ChatChannel.company_id == company_id,
                    ChatChannel.kind == ChatChannelKind.direct,
                )
            )
        ).all()
        assert len(directs) == 1
        # The DM has the agent and the founder as participants.
        parts = await chat.participants(db, directs[0].id)
        agent_ids = {p.agent_id for p in parts}
        assert agent.id in agent_ids and None in agent_ids
        # Re-DMing the same teammate reuses the thread (no duplicate channel).
        out2 = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="message_teammate",
            args={"to": "founder", "message": "Following up."},
        )
        await db.commit()
        assert not out2.is_error
        again = await db.scalar(
            select(func.count(ChatChannel.id)).where(
                ChatChannel.company_id == company_id,
                ChatChannel.kind == ChatChannelKind.direct,
            )
        )
        assert again == 1


# ── Decision ⇄ chat consolidation ─────────────────────────────────────────────
@requires_db
async def test_request_decision_is_founder_dm_resumed_by_reply(
    session_factory, company_with_budget
):
    """An open-ended decision is a founder DM; the founder's chat reply resumes it."""
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id, role=AgentRole.ceo)

    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="request_decision",
            args={"kind": "strategy", "summary": "Pivot to enterprise — your call?"},
        )
        await db.commit()
    assert out.park is True

    # Founder replies in the agent's DM thread (the unified inbox).
    async with session_factory() as db:
        channel = await chat.founder_dm(db, company_id=company_id, agent_id=agent.id)
        _, woken = await chat.post_message(
            db,
            company_id=company_id,
            channel_id=channel.id,
            sender_agent_id=None,
            body="Yes, pivot.",
        )
        await db.commit()
    assert task.id in woken

    # Resume: re-issued request_decision delivers the founder's reply, no re-post.
    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="request_decision",
            args={"kind": "strategy", "summary": "Pivot to enterprise — your call?"},
        )
        await db.commit()
    assert out.park is False
    assert "Yes, pivot." in out.observation


@requires_db
async def test_structured_decision_surfaces_as_dm(session_factory, company_with_budget):
    """submit_plan keeps its DecisionRequest grant but also appears in a founder DM."""
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id, role=AgentRole.ceo)

    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="submit_plan",
            args={"plan": "Ship the MVP, then run growth experiments."},
        )
        await db.commit()
    assert out.park is True

    async with session_factory() as db:
        decision = await db.scalar(
            select(DecisionRequest).where(DecisionRequest.task_id == task.id)
        )
        # The structured decision (with its grant payload) still exists...
        assert decision is not None
        assert decision.kind is DecisionKind.plan_approval
        # ...and is linked to the founder DM thread, where the plan was posted.
        assert decision.channel_id is not None
        msgs = await chat.messages(db, channel_id=decision.channel_id)
        assert any("Ship the MVP" in m.body for m in msgs)
