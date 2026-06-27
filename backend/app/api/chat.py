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

from app.deps import CompanyDep, DbDep
from app.models import Agent, ChatChannel, ChatMessage, ChatWait, DecisionRequest
from app.models.enums import AgentRole, ChatWaitStatus, DecisionStatus
from app.runtime.queue import enqueue_task
from app.schemas import (
    ChatChannelCreateRequest,
    ChatChannelOut,
    ChatMessageOut,
    ChatParticipantOut,
    ChatPostRequest,
    DecisionOut,
)
from app.services import chat

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
):
    channel = await _load_channel(db, company, channel_id)
    msgs = await chat.messages(db, channel_id=channel.id, limit=limit)
    return [await _message_out(db, m) for m in msgs]


@router.post("/channels/{channel_id}/messages", response_model=ChatMessageOut)
async def post_message(
    company: CompanyDep, channel_id: uuid.UUID, body: ChatPostRequest, db: DbDep
):
    channel = await _load_channel(db, company, channel_id)
    message, woken = await chat.post_message(
        db,
        company_id=company.id,
        channel_id=channel.id,
        sender_agent_id=None,  # the founder is replying
        body=body.message,
    )
    await db.commit()
    # Resume any agents that were waiting for this reply.
    for task_id in woken:
        await enqueue_task(task_id)
    return await _message_out(db, message)
