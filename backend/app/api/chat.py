"""Founder-facing chat: read the fleet's channels and reply to waiting agents.

This is the human side of the collaboration layer in :mod:`app.services.chat`.
The founder can browse every channel and direct thread, open new channels, and
post messages. Posting is the founder's lever for the reply-wait mechanic: when an
agent is parked waiting for an answer (``waiting_agents`` on the channel), the
founder's message satisfies that wait and re-queues the agent's task — the chat
analog of approving a decision.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent, ChatChannel, ChatMessage, ChatWait, DecisionRequest
from app.models.enums import AgentRole, ChatChannelKind, ChatWaitStatus, DecisionStatus
from app.runtime.queue import enqueue_task
from app.schemas import (
    ChatChannelCreateRequest,
    ChatChannelOut,
    ChatMessageOut,
    ChatParticipantOut,
    ChatPostRequest,
    ChatThreadOut,
    DecisionOut,
)
from app.services import chat
from app.services import decisions as decisions_svc

router = APIRouter(prefix="/companies/{company_id}/chat", tags=["chat"])


async def _channel_out(db, channel: ChatChannel) -> ChatChannelOut:
    """Enrich a channel with participants, activity, and who's waiting on a reply."""
    out = ChatChannelOut.model_validate(channel)

    parts = await chat.participants(db, channel.id)
    participants_out: list[ChatParticipantOut] = []
    for p in parts:
        if p.agent_id is None:
            participants_out.append(ChatParticipantOut(name=chat.FOUNDER_LABEL))
        else:
            agent = await db.get(Agent, p.agent_id)
            participants_out.append(
                ChatParticipantOut(
                    agent_id=p.agent_id,
                    name=agent.name if agent else "Unknown agent",
                    role=agent.role.value if agent else None,
                )
            )
    out.participants = participants_out

    out.message_count = (
        await db.scalar(
            select(func.count(ChatMessage.id)).where(ChatMessage.channel_id == channel.id)
        )
        or 0
    )
    recent = await chat.messages(db, channel_id=channel.id, limit=1)
    if recent:
        last = recent[-1]
        out.last_message_at = last.created_at
        label = await chat.sender_label(db, last)
        out.last_message_preview = f"{label}: {last.body[:120]}"

    # Open threads (sub-conversations) so the founder can browse and reply into them.
    threads_out: list[ChatThreadOut] = []
    for th in await chat.threads_for_channel(db, channel_id=channel.id):
        item = ChatThreadOut.model_validate(th)
        item.message_count = await chat.message_count(
            db, channel_id=channel.id, thread_id=th.id
        )
        trecent = await chat.messages(db, channel_id=channel.id, thread_id=th.id, limit=1)
        if trecent:
            item.last_message_at = trecent[-1].created_at
        threads_out.append(item)
    out.threads = threads_out

    # Agents parked waiting for a reply here — the founder's "needs you" signal.
    waiting = (
        await db.scalars(
            select(ChatWait).where(
                ChatWait.channel_id == channel.id,
                ChatWait.status == ChatWaitStatus.pending,
            )
        )
    ).all()
    names: list[str] = []
    for w in waiting:
        if w.agent_id is None:
            continue
        agent = await db.get(Agent, w.agent_id)
        if agent is not None:
            names.append(f"{agent.name} ({agent.role.value})")
    out.waiting_agents = names

    # A structured decision (budget/plan/hire/external) parked in this thread —
    # the founder resolves it with Approve/Reject inline.
    decision = await db.scalar(
        select(DecisionRequest)
        .where(
            DecisionRequest.channel_id == channel.id,
            DecisionRequest.status == DecisionStatus.pending,
        )
        .order_by(DecisionRequest.created_at.desc())
        .limit(1)
    )
    if decision is not None:
        item = DecisionOut.model_validate(decision)
        agent = await db.get(Agent, decision.agent_id) if decision.agent_id else None
        item.agent_name = agent.name if agent else None
        item.agent_role = agent.role.value if agent else None
        out.pending_decision = item
    return out


async def _message_out(db, message: ChatMessage) -> ChatMessageOut:
    out = ChatMessageOut.model_validate(message)
    out.is_founder = message.sender_agent_id is None
    if message.sender_agent_id is not None:
        agent = await db.get(Agent, message.sender_agent_id)
        out.sender_name = agent.name if agent else None
        out.sender_role = agent.role.value if agent else None
    else:
        out.sender_name = chat.FOUNDER_LABEL
    return out


async def _load_channel(db, company: CompanyDep, channel_id: uuid.UUID) -> ChatChannel:
    channel = await db.get(ChatChannel, channel_id)
    if channel is None or channel.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Channel not found")
    return channel


@router.get("/channels", response_model=list[ChatChannelOut])
async def list_channels(company: CompanyDep, db: DbDep):
    # The founder's direct line to the CEO always exists (created on first use),
    # so it's there to open by default and message at any time.
    if await chat.ensure_ceo_dm(db, company_id=company.id) is not None:
        await db.commit()
    channels = (
        await db.scalars(
            select(ChatChannel)
            .where(ChatChannel.company_id == company.id, ChatChannel.archived.is_(False))
            .order_by(ChatChannel.created_at.desc())
            .limit(100)
        )
    ).all()
    return [await _channel_out(db, ch) for ch in channels]


@router.post("/channels", response_model=ChatChannelOut)
async def create_channel(company: CompanyDep, body: ChatChannelCreateRequest, db: DbDep):
    # Resolve requested member roles to one active agent each.
    member_ids: list[uuid.UUID] = []
    for raw in body.member_roles:
        try:
            role = AgentRole(str(raw).lower())
        except ValueError:
            continue
        agent = await db.scalar(
            select(Agent)
            .where(Agent.company_id == company.id, Agent.role == role)
            .order_by(Agent.created_at)
            .limit(1)
        )
        if agent is not None:
            member_ids.append(agent.id)

    channel = await chat.create_channel(
        db,
        company_id=company.id,
        name=body.name,
        purpose=body.purpose,
        created_by_agent_id=None,  # the founder
        member_agent_ids=member_ids,
    )
    await db.commit()
    return await _channel_out(db, channel)


@router.get("/channels/{channel_id}/messages", response_model=list[ChatMessageOut])
async def list_messages(
    company: CompanyDep,
    channel_id: uuid.UUID,
    db: DbDep,
    limit: int = Query(default=200, le=500),
    thread_id: uuid.UUID | None = Query(default=None),
):
    """Messages in the channel's main timeline, or in one thread (``thread_id``)."""
    channel = await _load_channel(db, company, channel_id)
    msgs = await chat.messages(db, channel_id=channel.id, thread_id=thread_id, limit=limit)
    return [await _message_out(db, m) for m in msgs]


@router.post("/channels/{channel_id}/messages", response_model=ChatMessageOut)
async def post_message(
    company: CompanyDep,
    channel_id: uuid.UUID,
    body: ChatPostRequest,
    db: DbDep,
    user: CurrentUser,
):
    channel = await _load_channel(db, company, channel_id)
    message, woken = await chat.post_message(
        db,
        company_id=company.id,
        channel_id=channel.id,
        sender_agent_id=None,  # the founder is replying
        body=body.message,
        thread_id=body.thread_id,
    )

    # A structured decision (budget/hire/plan/external) has no separate widget: the
    # founder resolves it by replying here. Classify this reply and, if it clearly
    # approves or rejects the channel's pending decision, resolve it and resume the
    # owning task — the same path the game's approve/reject buttons take. An
    # ambiguous reply (a question/aside) leaves the decision open and falls through
    # to the normal DM-steering behaviour below. Decisions live on the main
    # timeline, so only main-timeline replies can resolve one.
    resumed_decision_task: uuid.UUID | None = None
    decision_verdict = "none"
    if body.thread_id is None:
        resumed_decision_task, decision_verdict = await decisions_svc.try_resolve_from_reply(
            db,
            company_id=company.id,
            channel_id=channel.id,
            reply=body.message,
            user_id=user.id,
        )

    # If this is a 1:1 DM with an agent and the founder's message didn't resume a
    # parked agent or settle a decision, wake that agent with a fresh task so it
    # reads and acts on the message — e.g. the founder steering the CEO live. The
    # spawn coalesces if a task is already handling the DM. This also fires when
    # ``decision_verdict == "unclear"``: the reply didn't clearly approve/reject the
    # channel's pending decision (a clarification was already posted), but it may
    # still be the founder steering the agent directly on something unrelated — e.g.
    # a functional agent that has an old pending decision sitting in its DM. Without
    # this, that message is silently dropped: no decision gets resolved (stays
    # pending) and no task reads it either. Spawning lets the agent read the full
    # channel — including the still-open decision — and act on both.
    spawned: uuid.UUID | None = None
    if (
        not woken
        and resumed_decision_task is None
        and decision_verdict in ("none", "unclear")
        and channel.kind == ChatChannelKind.direct
        and body.thread_id is None
    ):
        agent_members = [
            p.agent_id for p in await chat.participants(db, channel.id) if p.agent_id is not None
        ]
        if len(agent_members) == 1:
            spawned = await chat.spawn_dm_handler_task(
                db,
                company_id=company.id,
                channel=channel,
                agent_id=agent_members[0],
                founder_message=body.message,
            )

    await db.commit()
    # Resume any agents that were waiting for this reply.
    for task_id in woken:
        await enqueue_task(task_id)
    if resumed_decision_task is not None:
        await enqueue_task(resumed_decision_task)
    if spawned is not None:
        await enqueue_task(spawned)
    return await _message_out(db, message)
