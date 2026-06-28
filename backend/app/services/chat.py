"""Chat collaboration service: channels, messages, and the reply-wait mechanic.

The fleet (and the founder) talk here. Two shapes of conversation, both backed by
:class:`app.models.chat.ChatChannel`:

- a named ``channel`` for a big initiative several agents collaborate on, and
- a 1:1 ``direct`` thread (find-or-created between two participants).

A participant or message author with ``agent_id IS NULL`` is **the founder**.

The heart of the module is :func:`post_message`: every new message — whoever
sends it — satisfies any *other* participant's pending :class:`ChatWait` in that
channel and re-queues their parked task. That is what lets an agent block on a
reply the same way it blocks on a founder decision (see ``app.runtime.tools.chat``
for the agent side and ``app.api.chat`` for the founder side). Callers are
responsible for committing and then enqueuing the returned woken task ids.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Agent,
    ChatChannel,
    ChatMessage,
    ChatParticipant,
    ChatWait,
    Task,
)
from app.models.enums import (
    AgentRole,
    AgentStatus,
    ChatChannelKind,
    ChatWaitStatus,
    TaskStatus,
)

#: How the founder appears in rendered transcripts / participant lists.
FOUNDER_LABEL = "Founder"


# ── Participants ──────────────────────────────────────────────────────────────
async def _ensure_participant(
    db: AsyncSession, *, company_id: uuid.UUID, channel_id: uuid.UUID, agent_id: uuid.UUID | None
) -> None:
    """Add ``agent_id`` (``None`` = the founder) to the channel if not already in.

    Idempotent: collaboration is fluid, so posting to a channel you're not yet a
    member of simply adds you rather than erroring.
    """
    stmt = select(ChatParticipant.id).where(ChatParticipant.channel_id == channel_id)
    stmt = stmt.where(
        ChatParticipant.agent_id.is_(None)
        if agent_id is None
        else ChatParticipant.agent_id == agent_id
    )
    if await db.scalar(stmt) is None:
        db.add(ChatParticipant(company_id=company_id, channel_id=channel_id, agent_id=agent_id))


async def participants(db: AsyncSession, channel_id: uuid.UUID) -> list[ChatParticipant]:
    return list(
        (
            await db.scalars(
                select(ChatParticipant)
                .where(ChatParticipant.channel_id == channel_id)
                .order_by(ChatParticipant.created_at.asc())
            )
        ).all()
    )


# ── Channels ──────────────────────────────────────────────────────────────────
async def create_channel(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    name: str,
    purpose: str | None = None,
    kind: ChatChannelKind = ChatChannelKind.channel,
    created_by_agent_id: uuid.UUID | None = None,
    member_agent_ids: list[uuid.UUID] | None = None,
    include_founder: bool = True,
) -> ChatChannel:
    """Open a channel and seed its participants (creator + members + founder)."""
    channel = ChatChannel(
        company_id=company_id,
        name=name.strip()[:255] or "channel",
        purpose=(purpose or None),
        kind=kind,
        created_by_agent_id=created_by_agent_id,
    )
    db.add(channel)
    await db.flush()

    members: set[uuid.UUID] = set(member_agent_ids or [])
    if created_by_agent_id is not None:
        members.add(created_by_agent_id)
    for agent_id in members:
        await _ensure_participant(
            db, company_id=company_id, channel_id=channel.id, agent_id=agent_id
        )
    if include_founder:
        await _ensure_participant(db, company_id=company_id, channel_id=channel.id, agent_id=None)
    await db.flush()
    return channel


async def find_channel_by_name(
    db: AsyncSession, *, company_id: uuid.UUID, name: str
) -> ChatChannel | None:
    """Resolve a non-archived channel by case-insensitive name (newest wins)."""
    return await db.scalar(
        select(ChatChannel)
        .where(
            ChatChannel.company_id == company_id,
            func.lower(ChatChannel.name) == name.strip().lower(),
            ChatChannel.archived.is_(False),
        )
        .order_by(ChatChannel.created_at.desc())
        .limit(1)
    )


async def get_or_create_direct(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    agent_a_id: uuid.UUID | None,
    agent_b_id: uuid.UUID | None,
    name: str,
) -> ChatChannel:
    """Find (or open) the 1:1 thread between two participants.

    ``None`` for either side means the founder. Reuses an existing direct channel
    whose participant set is exactly the two parties, so repeated DMs land in one
    continuous thread instead of spawning duplicates.
    """
    want = {agent_a_id, agent_b_id}
    directs = (
        await db.scalars(
            select(ChatChannel).where(
                ChatChannel.company_id == company_id,
                ChatChannel.kind == ChatChannelKind.direct,
                ChatChannel.archived.is_(False),
            )
        )
    ).all()
    for channel in directs:
        member_ids = {p.agent_id for p in await participants(db, channel.id)}
        if member_ids == want:
            return channel
    return await create_channel(
        db,
        company_id=company_id,
        name=name,
        kind=ChatChannelKind.direct,
        created_by_agent_id=agent_a_id,
        member_agent_ids=[a for a in (agent_a_id, agent_b_id) if a is not None],
        # The founder is only a member of a direct thread when they are a party to
        # it (one side is None), not by default.
        include_founder=(agent_a_id is None or agent_b_id is None),
    )


# ── Messages + the reply-wait mechanic ────────────────────────────────────────
async def post_message(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    channel_id: uuid.UUID,
    sender_agent_id: uuid.UUID | None,
    body: str,
) -> tuple[ChatMessage, list[uuid.UUID]]:
    """Append a message and satisfy any *other* participant's pending wait.

    Returns ``(message, woken_task_ids)``. The caller must commit, then enqueue
    each woken task id so the parked agents resume and pick up the reply. A wait is
    never satisfied by its own author's message, so an agent isn't woken by itself.
    """
    message = ChatMessage(
        company_id=company_id,
        channel_id=channel_id,
        sender_agent_id=sender_agent_id,
        body=body,
    )
    db.add(message)
    if sender_agent_id is not None:
        await _ensure_participant(
            db, company_id=company_id, channel_id=channel_id, agent_id=sender_agent_id
        )
    await db.flush()

    waits = (
        await db.scalars(
            select(ChatWait).where(
                ChatWait.channel_id == channel_id,
                ChatWait.status == ChatWaitStatus.pending,
            )
        )
    ).all()
    woken: list[uuid.UUID] = []
    for wait in waits:
        # An agent's own post never wakes it (it's waiting for someone *else*).
        if wait.agent_id is not None and wait.agent_id == sender_agent_id:
            continue
        wait.status = ChatWaitStatus.satisfied
        task = await db.get(Task, wait.task_id)
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            task.status = TaskStatus.queued
            woken.append(task.id)
    await db.flush()
    return message, woken


async def message_count(db: AsyncSession, *, channel_id: uuid.UUID) -> int:
    """How many messages a channel holds — the value the loop guard caps."""
    return int(
        await db.scalar(
            select(func.count(ChatMessage.id)).where(ChatMessage.channel_id == channel_id)
        )
        or 0
    )


async def wake_channel_waiters(
    db: AsyncSession, *, channel_id: uuid.UUID, exclude_agent_id: uuid.UUID | None = None
) -> list[uuid.UUID]:
    """Satisfy and re-queue every pending wait in a channel without posting.

    Used when the discussion is throttled or closed: an agent parked waiting for a
    reply must not be stranded just because posting was paused, so its wait is
    satisfied (it resumes, finds whatever was already said, and carries on). The
    caller commits, then enqueues the returned task ids. ``exclude_agent_id`` keeps
    a given agent parked (e.g. the one that just hit the cap).
    """
    waits = (
        await db.scalars(
            select(ChatWait).where(
                ChatWait.channel_id == channel_id,
                ChatWait.status == ChatWaitStatus.pending,
            )
        )
    ).all()
    woken: list[uuid.UUID] = []
    for wait in waits:
        if exclude_agent_id is not None and wait.agent_id == exclude_agent_id:
            continue
        wait.status = ChatWaitStatus.satisfied
        task = await db.get(Task, wait.task_id)
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            task.status = TaskStatus.queued
            woken.append(task.id)
    await db.flush()
    return woken


async def escalate_channel_to_ceo(
    db: AsyncSession,
    *,
    channel: ChatChannel,
    attempted_by: Agent,
    attempted_body: str,
    run_id: uuid.UUID,
    root_run_id: uuid.UUID,
    parent_task_id: uuid.UUID | None,
    depth: int,
) -> tuple[uuid.UUID | None, list[uuid.UUID]]:
    """Pause a channel that hit its message budget and wake the CEO to rule on it.

    The loop guard's escalation path: flips ``escalation_pending`` so further posts
    are held, creates a CEO review task (the CEO extends the discussion or ends it
    with ``extend_chat_channel``), and wakes any agents parked waiting in the
    channel so the pause can't strand them. Returns ``(ceo_task_id, woken_task_ids)``
    for the caller to enqueue; ``ceo_task_id`` is ``None`` when there is no active
    CEO to escalate to (the caller then lets the post through rather than deadlock).
    """
    from app.runtime import breakers  # local import avoids a service↔runtime cycle

    ceo = await db.scalar(
        select(Agent).where(
            Agent.company_id == channel.company_id,
            Agent.role == AgentRole.ceo,
            Agent.status == AgentStatus.active,
        )
    )
    if ceo is None:
        return None, []

    channel.escalation_pending = True
    await db.flush()

    recent = await messages(db, channel_id=channel.id, limit=10)
    lines = [render_message(m, await sender_label(db, m)) for m in recent]
    transcript = "\n".join(lines)
    count = await message_count(db, channel_id=channel.id)
    purpose = f" — {channel.purpose}" if channel.purpose else ""
    preview = (attempted_body or "").strip()[:200]
    goal = (
        f"A team chat discussion in #{channel.name}{purpose} has reached its "
        f"{channel.message_budget}-message limit and is PAUSED for your review. This guard "
        "keeps collaboration distributed across the team while making sure two agents can't "
        "get stuck in an endless back-and-forth.\n\n"
        f"{count} messages so far. Most recent:\n{transcript}\n\n"
        f'{attempted_by.name} ({attempted_by.role.value}) was about to post: "{preview}"\n\n'
        "Judge whether this is productive collaboration worth continuing or an unproductive "
        "loop that should stop, then decide:\n"
        f'- To let it continue, call `extend_chat_channel` with channel "{channel.name}" and '
        "`additional_messages` set to how many more messages to allow before the next review "
        "(e.g. 10 for a focused topic, more for a big initiative).\n"
        f'- To end it, call `extend_chat_channel` with channel "{channel.name}" and '
        "`additional_messages` 0 — that closes the channel.\n"
        "Then finish with `report_result`."
    )
    review = Task(
        company_id=channel.company_id,
        run_id=run_id,
        root_run_id=root_run_id,
        agent_id=ceo.id,
        parent_task_id=parent_task_id,
        depth=depth,
        goal=goal,
        input={"chat_escalation_channel_id": str(channel.id)},
        status=TaskStatus.queued,
        loop_signature=breakers.loop_signature(
            ceo.id, f"chat-escalation {channel.id} b{channel.message_budget}"
        ),
    )
    db.add(review)
    await db.flush()
    # Don't strand the agent that just hit the cap — it stays parked on its own send
    # (it will deliver whatever lands once the CEO rules); free everyone else.
    woken = await wake_channel_waiters(
        db, channel_id=channel.id, exclude_agent_id=attempted_by.id
    )
    return review.id, woken


async def messages(
    db: AsyncSession, *, channel_id: uuid.UUID, limit: int = 100
) -> list[ChatMessage]:
    """The most recent ``limit`` messages in a channel, oldest-first for display."""
    rows = (
        await db.scalars(
            select(ChatMessage)
            .where(ChatMessage.channel_id == channel_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(limit)
        )
    ).all()
    return list(reversed(rows))


async def replies_for_wait(
    db: AsyncSession, *, wait: ChatWait, limit: int = 50
) -> list[ChatMessage]:
    """Messages that satisfied a wait: later posts from anyone but the waiter."""
    stmt = select(ChatMessage).where(
        ChatMessage.channel_id == wait.channel_id,
        ChatMessage.created_at >= wait.created_at,
    )
    if wait.agent_id is not None:
        stmt = stmt.where(
            (ChatMessage.sender_agent_id.is_(None)) | (ChatMessage.sender_agent_id != wait.agent_id)
        )
    rows = (await db.scalars(stmt.order_by(ChatMessage.created_at.asc()).limit(limit))).all()
    return list(rows)


async def pending_wait_for_task(
    db: AsyncSession, *, task_id: uuid.UUID, channel_id: uuid.UUID
) -> ChatWait | None:
    """The live (pending/satisfied) wait this task holds on a channel, if any.

    Used on resume so a re-run ``send_chat_message`` delivers the reply instead of
    re-posting — the chat analog of a one-shot approval grant.
    """
    return await db.scalar(
        select(ChatWait)
        .where(
            ChatWait.task_id == task_id,
            ChatWait.channel_id == channel_id,
            ChatWait.status.in_((ChatWaitStatus.pending, ChatWaitStatus.satisfied)),
        )
        .order_by(ChatWait.created_at.desc())
        .limit(1)
    )


def render_message(message: ChatMessage, sender_label: str) -> str:
    return f"{sender_label}: {message.body}"


async def sender_label(db: AsyncSession, message: ChatMessage) -> str:
    """Human label for a message author (``Founder`` or ``Name (role)``)."""
    if message.sender_agent_id is None:
        return FOUNDER_LABEL
    agent = await db.get(Agent, message.sender_agent_id)
    if agent is None:
        return "Unknown agent"
    return f"{agent.name} ({agent.role.value})"


# ── Decisions as founder DMs ──────────────────────────────────────────────────
async def founder_dm(
    db: AsyncSession, *, company_id: uuid.UUID, agent_id: uuid.UUID
) -> ChatChannel:
    """The direct thread between an agent and the founder (created on first use).

    This is where an agent's escalations land: the unified "decision inbox" is just
    each agent's DM thread with the founder.
    """
    agent = await db.get(Agent, agent_id)
    label = f"{agent.role.value} agent" if agent else "agent"
    return await get_or_create_direct(
        db,
        company_id=company_id,
        agent_a_id=agent_id,
        agent_b_id=None,
        name=f"{label} ↔ founder",
    )


async def post_decision_dm(
    db: AsyncSession, *, company_id: uuid.UUID, agent_id: uuid.UUID, summary: str
) -> tuple[ChatChannel, ChatMessage]:
    """Surface a structured decision as a message in the agent↔founder DM.

    Used by escalations that still need the :class:`DecisionRequest` grant
    machinery (budget/plan/hire/external). The returned channel id is stored on the
    decision so resolving it can post a reply back into the same thread. Does NOT
    create a :class:`ChatWait` — the pending decision itself is the "waiting"
    marker, and resolution flows through approve/reject, not a chat reply.
    """
    channel = await founder_dm(db, company_id=company_id, agent_id=agent_id)
    message = ChatMessage(
        company_id=company_id,
        channel_id=channel.id,
        sender_agent_id=agent_id,
        body=summary,
    )
    db.add(message)
    await db.flush()
    return channel, message


async def attach_decision_dm(db: AsyncSession, *, decision) -> ChatChannel | None:
    """Mirror a structured :class:`DecisionRequest` into the agent↔founder DM.

    Posts the decision summary as a message in the thread and records the channel
    on the decision, so it shows up in chat marked "waiting for a response" and its
    resolution can be posted back. No-op for an agentless decision. Call after the
    decision row has been flushed (so it has an id).
    """
    if decision.agent_id is None:
        return None
    channel, _ = await post_decision_dm(
        db, company_id=decision.company_id, agent_id=decision.agent_id, summary=decision.summary
    )
    decision.channel_id = channel.id
    await db.flush()
    return channel


async def post_system_reply(
    db: AsyncSession, *, company_id: uuid.UUID, channel_id: uuid.UUID, body: str
) -> ChatMessage:
    """Post a founder-side resolution note into a decision's DM thread.

    Recorded as a founder message (``sender_agent_id`` NULL) so the thread reads as
    the founder answering. Deliberately bypasses :func:`post_message`'s wait
    satisfaction — structured decisions resume via approve/reject, so this is a
    display-only follow-up that must not also wake the task.
    """
    message = ChatMessage(
        company_id=company_id, channel_id=channel_id, sender_agent_id=None, body=body
    )
    db.add(message)
    await db.flush()
    return message
