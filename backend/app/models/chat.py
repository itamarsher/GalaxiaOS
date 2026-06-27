"""In-house chat: channels, participants, messages, and reply-waits.

This is the fleet's collaboration layer. Agents and the founder talk to each
other here: ad-hoc 1:1 threads (``direct``) and named channels for big
initiatives that need cross-agent collaboration (``channel``). Throughout, a
participant/sender with ``agent_id IS NULL`` is **the founder** — the human stays
a first-class chat member without a synthetic agent row.

The reply-wait mechanic mirrors the founder decision inbox (see
:class:`app.models.governance.DecisionRequest`): an agent can post a message and
*wait* for an answer. A :class:`ChatWait` parks the agent's task until someone
else posts to the channel, at which point the wait is satisfied and the task is
re-queued — so an agent can block on another agent's (or the founder's) reply the
same way it blocks on a founder approval.
"""

from __future__ import annotations

import uuid

from sqlalchemy import (
    Boolean,
    Enum,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import ChatChannelKind, ChatWaitStatus


class ChatChannel(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "chat_channels"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # What the channel is for (the initiative it coordinates); free text.
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[ChatChannelKind] = mapped_column(
        Enum(ChatChannelKind, native_enum=False, length=20),
        default=ChatChannelKind.channel,
        nullable=False,
    )
    # Who opened it; NULL = the founder.
    created_by_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ChatParticipant(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "chat_participants"
    __table_args__ = (
        # One row per (channel, member); ``agent_id NULL`` (the founder) is unique
        # per channel too — Postgres treats a single NULL as distinct, which is the
        # behaviour we want (only one founder participant row per channel).
        UniqueConstraint("channel_id", "agent_id", name="uq_chat_participant"),
    )

    channel_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The member agent; NULL = the founder.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )


class ChatMessage(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "chat_messages"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The author; NULL = the founder.
    sender_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)


class ChatWait(Base, PKMixin, TenantMixin, TimestampMixin):
    """A parked task waiting for someone to reply in a channel.

    Created when an agent posts with ``wait_for_reply``; its task is flipped to
    ``waiting_approval`` (the same parked state decisions use) until another
    participant posts, which satisfies the wait and re-queues the task. The
    boundary for "what counts as a reply" is the wait's ``created_at``: any later
    message from someone other than the waiting agent.
    """

    __tablename__ = "chat_waits"

    channel_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_channels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[ChatWaitStatus] = mapped_column(
        Enum(ChatWaitStatus, native_enum=False, length=20),
        default=ChatWaitStatus.pending,
        nullable=False,
        index=True,
    )
