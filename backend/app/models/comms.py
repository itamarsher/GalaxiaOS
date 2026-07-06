"""Outbound external-communication index.

Every message an agent tries to send *outside* the company — an email, a social
post, a published page, an ad, a notification — is recorded here as it passes
through the agent loop's single tool chokepoint. The index is the durable record
the founder reads to audit what the fleet has said to the world, and it is the
backing store for the "every external communication needs founder approval"
policy: a gated message is parked here as ``pending_approval`` and linked to the
:class:`DecisionRequest` the founder discusses and resolves.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import ExternalMessageStatus


class ExternalMessage(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "external_messages"

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # The approval request this message is gated behind, when the policy required
    # one. Lets the founder jump from the message to its discussion thread.
    decision_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("decision_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    # The tool that emitted it (send_email, publish_content, …) and a coarse
    # channel (email, social, blog, notification, ad) for filtering/grouping.
    tool: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    # Best-effort human-readable addressing + content, lifted from the tool args
    # so the index is readable without re-deriving it from the raw payload.
    recipient: Mapped[str | None] = mapped_column(String(500), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # full tool args
    status: Mapped[ExternalMessageStatus] = mapped_column(
        Enum(ExternalMessageStatus, native_enum=False, length=20),
        default=ExternalMessageStatus.sent,
        nullable=False,
        index=True,
    )
    # Provider observation / error string (e.g. "sent via resend (id …)").
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
