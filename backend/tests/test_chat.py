"""Tests for the chat collaboration layer and the reply-wait mechanic.

Covers the agent tools (open a channel, post, DM), the parking flow when an agent
waits for a reply (mirroring the founder-decision parking), and the resume path
where a teammate's or the founder's reply wakes the parked task and is delivered
to the agent without re-posting the original message.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.models import (
    Agent,
    AgentRun,
    ChatChannel,
    ChatMessage,
    ChatThread,
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
    # A founder reply always carries the confirmation directive back to the agent.
    assert chat.FOUNDER_ACK_DIRECTIVE in out.observation

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

    # Resume the waiter: a teammate (non-founder) reply is delivered WITHOUT the
    # founder confirmation directive — that's reserved for founder messages.
    async with session_factory() as db:
        out = await execute_tool(
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
    assert "~$2B." in out.observation
    assert chat.FOUNDER_ACK_DIRECTIVE not in out.observation


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


# ── Loop guard: message budget + CEO escalation ───────────────────────────────
async def _set_budget(session_factory, channel_id, budget: int) -> None:
    async with session_factory() as db:
        ch = await db.get(ChatChannel, channel_id)
        ch.message_budget = budget
        await db.commit()


async def _post(session_factory, *, agent, task, channel="war-room", message="hi", thread=None, ctx=None):
    ctx = ctx or FakeCtx()
    args = {"channel": channel, "message": message}
    if thread is not None:
        args["thread"] = thread
    async with session_factory() as db:
        out = await execute_tool(
            db, ctx, agent=agent, task=task, name="send_chat_message", args=args
        )
        await db.commit()
    return out, ctx


async def _set_thread_budget(session_factory, thread_id, budget: int) -> None:
    async with session_factory() as db:
        th = await db.get(ChatThread, thread_id)
        th.message_budget = budget
        await db.commit()


@requires_db
async def test_channel_throttle_escalates_to_ceo(session_factory, company_with_budget):
    """Once a channel hits its message budget, the next post pauses it and wakes the CEO."""
    company_id = company_with_budget
    ceo, _ = await _agent_and_task(session_factory, company_id, role=AgentRole.ceo, name="Boss")
    agent, task = await _agent_and_task(session_factory, company_id, name="Grow")

    async with session_factory() as db:
        channel = await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=agent.id
        )
        await db.commit()
        channel_id = channel.id
    await _set_budget(session_factory, channel_id, 2)

    # Two posts fit under the budget.
    out1, _ = await _post(session_factory, agent=agent, task=task, message="one")
    out2, _ = await _post(session_factory, agent=agent, task=task, message="two")
    assert not out1.is_error and not out2.is_error

    # The third hits the cap: blocked, escalated, channel paused.
    out3, ctx = await _post(session_factory, agent=agent, task=task, message="three")
    assert not out3.is_error
    assert "CEO" in out3.observation and "paused" in out3.observation.lower()

    async with session_factory() as db:
        ch = await db.get(ChatChannel, channel_id)
        assert ch.escalation_pending is True
        # Only the two under-budget messages were posted; "three" was not.
        msgs = await chat.messages(db, channel_id=channel_id)
        assert [m.body for m in msgs] == ["one", "two"]
        # A CEO review task was created and enqueued (parented to the blocked post).
        review = await db.scalar(
            select(Task).where(
                Task.company_id == company_id,
                Task.agent_id == ceo.id,
                Task.parent_task_id == task.id,
            )
        )
        assert review is not None
        assert "war-room" in review.goal
        assert (review.input or {}).get("chat_escalation_channel_id") == str(channel_id)
        assert review.id in ctx.enqueued

    # While the review is open, further posts are held without re-escalating.
    out4, ctx4 = await _post(session_factory, agent=agent, task=task, message="four")
    assert "paused" in out4.observation.lower()
    async with session_factory() as db:
        # Still exactly one CEO review task (no duplicate escalation).
        count = await db.scalar(
            select(func.count(Task.id)).where(
                Task.company_id == company_id,
                Task.agent_id == ceo.id,
                Task.parent_task_id == task.id,
            )
        )
        assert count == 1


@requires_db
async def test_ceo_is_exempt_from_throttle(session_factory, company_with_budget):
    """The CEO referees the throttle, so their own posts are never capped."""
    company_id = company_with_budget
    ceo, ceo_task = await _agent_and_task(
        session_factory, company_id, role=AgentRole.ceo, name="Boss"
    )

    async with session_factory() as db:
        channel = await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=ceo.id
        )
        await db.commit()
        channel_id = channel.id
    await _set_budget(session_factory, channel_id, 1)

    # Post past the budget as the CEO — every one goes through, nothing escalates.
    for body in ("a", "b", "c"):
        out, _ = await _post(session_factory, agent=ceo, task=ceo_task, message=body)
        assert not out.is_error
    async with session_factory() as db:
        ch = await db.get(ChatChannel, channel_id)
        assert ch.escalation_pending is False
        msgs = await chat.messages(db, channel_id=channel_id)
        assert [m.body for m in msgs] == ["a", "b", "c"]


@requires_db
async def test_extend_chat_channel_resumes_discussion(session_factory, company_with_budget):
    """The CEO grants more messages; the channel un-pauses and posting works again."""
    company_id = company_with_budget
    ceo, ceo_task = await _agent_and_task(
        session_factory, company_id, role=AgentRole.ceo, name="Boss"
    )
    agent, task = await _agent_and_task(session_factory, company_id, name="Grow")

    async with session_factory() as db:
        channel = await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=agent.id
        )
        await db.commit()
        channel_id = channel.id
    await _set_budget(session_factory, channel_id, 1)

    await _post(session_factory, agent=agent, task=task, message="one")
    out_blocked, _ = await _post(session_factory, agent=agent, task=task, message="two")
    assert "paused" in out_blocked.observation.lower()

    # CEO extends the discussion by 3 messages.
    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=ceo,
            task=ceo_task,
            name="extend_chat_channel",
            args={"channel": "war-room", "additional_messages": 3},
        )
        await db.commit()
    assert not out.is_error
    assert "3 more" in out.observation

    async with session_factory() as db:
        ch = await db.get(ChatChannel, channel_id)
        assert ch.escalation_pending is False
        # Budget now allows 3 messages beyond everything posted so far (incl. the note).
        current = await chat.message_count(db, channel_id=channel_id)
        assert ch.message_budget == current + 3

    # The agent can post again.
    out_ok, _ = await _post(session_factory, agent=agent, task=task, message="resumed")
    assert not out_ok.is_error
    assert "paused" not in out_ok.observation.lower()


@requires_db
async def test_extend_chat_channel_zero_closes_it(session_factory, company_with_budget):
    """additional_messages=0 ends the discussion and archives the channel."""
    company_id = company_with_budget
    ceo, ceo_task = await _agent_and_task(
        session_factory, company_id, role=AgentRole.ceo, name="Boss"
    )
    agent, task = await _agent_and_task(session_factory, company_id, name="Grow")

    async with session_factory() as db:
        channel = await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=agent.id
        )
        await db.commit()
        channel_id = channel.id
    await _set_budget(session_factory, channel_id, 1)
    await _post(session_factory, agent=agent, task=task, message="one")
    await _post(session_factory, agent=agent, task=task, message="two")  # escalates

    async with session_factory() as db:
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=ceo,
            task=ceo_task,
            name="extend_chat_channel",
            args={"channel": "war-room", "additional_messages": 0, "reason": "Going in circles."},
        )
        await db.commit()
    assert not out.is_error
    assert "Closed" in out.observation

    async with session_factory() as db:
        ch = await db.get(ChatChannel, channel_id)
        assert ch.archived is True
        # Archived channels are no longer resolvable by name (closed to new posts).
        assert await chat.find_channel_by_name(db, company_id=company_id, name="war-room") is None


@requires_db
async def test_extend_chat_channel_is_ceo_only(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id, name="Grow")
    async with session_factory() as db:
        await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=agent.id
        )
        await db.commit()
        out = await execute_tool(
            db,
            FakeCtx(),
            agent=agent,
            task=task,
            name="extend_chat_channel",
            args={"channel": "war-room", "additional_messages": 5},
        )
        await db.commit()
    assert out.is_error
    assert "Only the CEO" in out.observation


# ── Threads: parallel sub-initiatives inside a channel ───────────────────────
@requires_db
async def test_send_to_thread_creates_isolated_subconversation(
    session_factory, company_with_budget
):
    """A thread message lands in its own sub-conversation, not the main timeline."""
    company_id = company_with_budget
    agent, task = await _agent_and_task(session_factory, company_id, name="Grow")
    async with session_factory() as db:
        channel = await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=agent.id
        )
        await db.commit()
        channel_id = channel.id

    await _post(session_factory, agent=agent, task=task, message="top-level")
    await _post(session_factory, agent=agent, task=task, message="in thread", thread="pricing")

    async with session_factory() as db:
        thread = await chat.find_thread_by_title(db, channel_id=channel_id, title="pricing")
        assert thread is not None
        # Main timeline holds only the top-level message; the thread holds its own.
        main = await chat.messages(db, channel_id=channel_id, thread_id=None)
        assert [m.body for m in main] == ["top-level"]
        tmsgs = await chat.messages(db, channel_id=channel_id, thread_id=thread.id)
        assert [m.body for m in tmsgs] == ["in thread"]
        assert tmsgs[0].thread_id == thread.id

    # read_chat_channel shows the main timeline and lists the thread (with a preview),
    # pointing the reader at read_chat_thread to drill in.
    async with session_factory() as db:
        out = await execute_tool(
            db, FakeCtx(), agent=agent, task=task,
            name="read_chat_channel", args={"channel": "war-room"},
        )
    assert "top-level" in out.observation
    assert "pricing" in out.observation  # thread is listed by title
    assert "read_chat_thread" in out.observation  # how to open it

    # read_chat_thread drills into the sub-conversation.
    async with session_factory() as db:
        out = await execute_tool(
            db, FakeCtx(), agent=agent, task=task,
            name="read_chat_thread", args={"channel": "war-room", "thread": "pricing"},
        )
    assert "in thread" in out.observation


@requires_db
async def test_thread_wait_is_isolated_from_other_scopes(session_factory, company_with_budget):
    """An agent waiting in a thread is woken only by a reply in that same thread."""
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

    # Waiter asks inside thread "alpha" and parks.
    async with session_factory() as db:
        await execute_tool(
            db, FakeCtx(), agent=waiter, task=waiter_task, name="send_chat_message",
            args={
                "channel": "collab", "message": "Q in alpha?",
                "thread": "alpha", "wait_for_reply": True,
            },
        )
        await db.commit()

    # A message on the main timeline must NOT wake the thread waiter.
    _, ctx_main = await _post(
        session_factory, agent=other, task=other_task, channel="collab", message="unrelated"
    )
    assert waiter_task.id not in ctx_main.enqueued
    async with session_factory() as db:
        row = await db.get(Task, waiter_task.id)
        assert row.status is TaskStatus.waiting_approval

    # A reply inside thread "alpha" DOES wake it.
    _, ctx_alpha = await _post(
        session_factory, agent=other, task=other_task,
        channel="collab", message="answer", thread="alpha",
    )
    assert waiter_task.id in ctx_alpha.enqueued
    async with session_factory() as db:
        row = await db.get(Task, waiter_task.id)
        assert row.status is TaskStatus.queued


@requires_db
async def test_thread_has_its_own_budget_and_escalates_independently(
    session_factory, company_with_budget
):
    """A runaway thread escalates on its own without pausing the rest of the channel."""
    company_id = company_with_budget
    ceo, _ = await _agent_and_task(session_factory, company_id, role=AgentRole.ceo, name="Boss")
    agent, task = await _agent_and_task(session_factory, company_id, name="Grow")
    async with session_factory() as db:
        channel = await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=agent.id
        )
        await db.commit()
        channel_id = channel.id

    await _post(session_factory, agent=agent, task=task, message="start", thread="alpha")
    async with session_factory() as db:
        thread = await chat.find_thread_by_title(db, channel_id=channel_id, title="alpha")
        thread_id = thread.id
    await _set_thread_budget(session_factory, thread_id, 1)

    # The main timeline is unaffected — the channel itself isn't throttled.
    out_main, _ = await _post(session_factory, agent=agent, task=task, message="channel ok")
    assert not out_main.is_error
    assert "paused" not in out_main.observation.lower()

    # The next post in the thread hits the thread's budget and escalates the thread.
    out, ctx = await _post(
        session_factory, agent=agent, task=task, message="more", thread="alpha"
    )
    assert "paused" in out.observation.lower()
    async with session_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert thread.escalation_pending is True
        channel = await db.get(ChatChannel, channel_id)
        assert channel.escalation_pending is False  # the channel stays open
        review = await db.scalar(
            select(Task).where(
                Task.company_id == company_id,
                Task.agent_id == ceo.id,
                Task.parent_task_id == task.id,
            )
        )
        assert review is not None
        assert (review.input or {}).get("chat_escalation_thread_id") == str(thread_id)
        assert "alpha" in review.goal
        assert review.id in ctx.enqueued


@requires_db
async def test_extend_chat_thread(session_factory, company_with_budget):
    """The CEO extends a specific thread, leaving the rest of the channel untouched."""
    company_id = company_with_budget
    ceo, ceo_task = await _agent_and_task(
        session_factory, company_id, role=AgentRole.ceo, name="Boss"
    )
    agent, task = await _agent_and_task(session_factory, company_id, name="Grow")
    async with session_factory() as db:
        channel = await chat.create_channel(
            db, company_id=company_id, name="war-room", created_by_agent_id=agent.id
        )
        await db.commit()
        channel_id = channel.id

    await _post(session_factory, agent=agent, task=task, message="start", thread="alpha")
    async with session_factory() as db:
        thread_id = (
            await chat.find_thread_by_title(db, channel_id=channel_id, title="alpha")
        ).id
    await _set_thread_budget(session_factory, thread_id, 1)
    out_blocked, _ = await _post(
        session_factory, agent=agent, task=task, message="more", thread="alpha"
    )
    assert "paused" in out_blocked.observation.lower()

    # CEO grants the thread 3 more messages.
    async with session_factory() as db:
        out = await execute_tool(
            db, FakeCtx(), agent=ceo, task=ceo_task, name="extend_chat_channel",
            args={"channel": "war-room", "thread": "alpha", "additional_messages": 3},
        )
        await db.commit()
    assert not out.is_error
    assert "3 more" in out.observation

    async with session_factory() as db:
        thread = await db.get(ChatThread, thread_id)
        assert thread.escalation_pending is False
        current = await chat.message_count(db, channel_id=channel_id, thread_id=thread_id)
        assert thread.message_budget == current + 3

    # The agent can post into the thread again.
    out_ok, _ = await _post(
        session_factory, agent=agent, task=task, message="resumed", thread="alpha"
    )
    assert "paused" not in out_ok.observation.lower()


# ── "Catch up on new chat" nudge watermark ────────────────────────────────────
@requires_db
async def test_chat_activity_nudges_only_about_others_since_watermark(
    session_factory, company_with_budget
):
    """The nudge lists new messages from teammates in the agent's channels, once."""
    company_id = company_with_budget
    me, my_task = await _agent_and_task(session_factory, company_id, name="Me")
    mate, mate_task = await _agent_and_task(
        session_factory, company_id, role=AgentRole.research, name="Mate"
    )
    async with session_factory() as db:
        await chat.create_channel(
            db, company_id=company_id, name="war-room",
            created_by_agent_id=me.id, member_agent_ids=[mate.id],
        )
        await db.commit()

    # My own earlier post sets the baseline; with since=None nothing is surfaced
    # (the loop just records the watermark on a fresh task without flooding it).
    await _post(session_factory, agent=me, task=my_task, message="mine")
    async with session_factory() as db:
        summary, baseline = await chat.chat_activity_for_agent(
            db, company_id=company_id, agent_id=me.id, since=None
        )
        assert summary is None
        assert baseline is not None

    # A teammate then posts (incl. in a thread) — that's what should be surfaced.
    await _post(session_factory, agent=mate, task=mate_task, message="theirs")
    await _post(session_factory, agent=mate, task=mate_task, message="in thread", thread="alpha")

    async with session_factory() as db:
        summary, newest = await chat.chat_activity_for_agent(
            db, company_id=company_id, agent_id=me.id, since=baseline
        )
    assert summary is not None
    assert "war-room" in summary
    assert "alpha" in summary  # the thread is named
    assert "read_chat_channel" in summary
    assert newest is not None

    # After advancing the watermark to `newest`, there's nothing new to surface.
    async with session_factory() as db:
        summary2, _ = await chat.chat_activity_for_agent(
            db, company_id=company_id, agent_id=me.id, since=newest
        )
    assert summary2 is None


@requires_db
async def test_chat_activity_ignores_channels_agent_is_not_in(
    session_factory, company_with_budget
):
    """An agent is only nudged about channels it belongs to."""
    company_id = company_with_budget
    me, _ = await _agent_and_task(session_factory, company_id, name="Me")
    other, other_task = await _agent_and_task(
        session_factory, company_id, role=AgentRole.research, name="Other"
    )
    # A channel `me` is NOT a member of.
    async with session_factory() as db:
        await chat.create_channel(
            db, company_id=company_id, name="not-mine", created_by_agent_id=other.id
        )
        await db.commit()
    await _post(session_factory, agent=other, task=other_task, channel="not-mine", message="hello")

    async with session_factory() as db:
        summary, _ = await chat.chat_activity_for_agent(
            db, company_id=company_id, agent_id=me.id,
            since=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )
    assert summary is None


# ── Founder ⇄ CEO standing DM ─────────────────────────────────────────────────
@requires_db
async def test_ensure_ceo_dm_creates_idempotent_founder_ceo_thread(
    session_factory, company_with_budget
):
    """The founder↔CEO DM is created once and reused — the standing steering line."""
    company_id = company_with_budget
    async with session_factory() as db:
        db.add(Agent(company_id=company_id, role=AgentRole.ceo, name="Boss"))
        await db.commit()

    async with session_factory() as db:
        dm = await chat.ensure_ceo_dm(db, company_id=company_id)
        await db.commit()
        assert dm is not None
        assert dm.kind is ChatChannelKind.direct
        # Founder is a participant of the DM.
        agent_ids = {p.agent_id for p in await chat.participants(db, dm.id)}
        assert None in agent_ids
        dm_id = dm.id

    # Calling again reuses the same thread (no duplicate DM).
    async with session_factory() as db:
        dm2 = await chat.ensure_ceo_dm(db, company_id=company_id)
        await db.commit()
        assert dm2.id == dm_id
        count = await db.scalar(
            select(func.count(ChatChannel.id)).where(
                ChatChannel.company_id == company_id,
                ChatChannel.kind == ChatChannelKind.direct,
            )
        )
        assert count == 1


@requires_db
async def test_founder_dm_spawns_handler_task_and_coalesces(
    session_factory, company_with_budget
):
    """Messaging an idle CEO spawns a task to act on it; a second message coalesces."""
    company_id = company_with_budget
    async with session_factory() as db:
        ceo = Agent(company_id=company_id, role=AgentRole.ceo, name="Boss")
        db.add(ceo)
        await db.flush()
        ceo_id = ceo.id
        await db.commit()

    async with session_factory() as db:
        dm = await chat.ensure_ceo_dm(db, company_id=company_id)
        await db.commit()
        dm_id = dm.id

    # Idle CEO → the founder's message spawns a queued handler task pointed at the DM.
    async with session_factory() as db:
        dm = await db.get(ChatChannel, dm_id)
        task_id = await chat.spawn_dm_handler_task(
            db,
            company_id=company_id,
            channel=dm,
            agent_id=ceo_id,
            founder_message="Shift focus to enterprise.",
        )
        await db.commit()
    assert task_id is not None

    async with session_factory() as db:
        t = await db.get(Task, task_id)
        assert t.agent_id == ceo_id
        assert t.status is TaskStatus.queued
        assert (t.input or {}).get("founder_dm_channel_id") == str(dm_id)
        assert "enterprise" in t.goal.lower()
        # The handler is required to confirm back what changed and what's next.
        assert chat.FOUNDER_ACK_DIRECTIVE in t.goal

    # A second message while that task is still open does NOT spawn a duplicate.
    async with session_factory() as db:
        dm = await db.get(ChatChannel, dm_id)
        again = await chat.spawn_dm_handler_task(
            db,
            company_id=company_id,
            channel=dm,
            agent_id=ceo_id,
            founder_message="Also trim spend.",
        )
        await db.commit()
    assert again is None


@requires_db
async def test_founder_dm_does_not_spawn_for_paused_agent(
    session_factory, company_with_budget
):
    """A paused agent isn't woken by a founder DM."""
    company_id = company_with_budget
    async with session_factory() as db:
        from app.models.enums import AgentStatus

        ceo = Agent(company_id=company_id, role=AgentRole.ceo, name="Boss", status=AgentStatus.paused)
        db.add(ceo)
        await db.flush()
        ceo_id = ceo.id
        await db.commit()

    async with session_factory() as db:
        dm = await chat.ensure_ceo_dm(db, company_id=company_id)
        await db.commit()
        dm_id = dm.id

    async with session_factory() as db:
        dm = await db.get(ChatChannel, dm_id)
        task_id = await chat.spawn_dm_handler_task(
            db, company_id=company_id, channel=dm, agent_id=ceo_id, founder_message="Hello?"
        )
        await db.commit()
    assert task_id is None


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
