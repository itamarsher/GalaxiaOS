"""Governance layer: policies, circuit breakers, reputation, decision requests."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import (
    BreakerState,
    BreakerType,
    DecisionKind,
    DecisionStatus,
    PolicyEffect,
    PolicyScope,
)


class Policy(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "policies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    scope: Mapped[PolicyScope] = mapped_column(
        Enum(PolicyScope, native_enum=False, length=20),
        default=PolicyScope.global_,
        nullable=False,
    )
    rule: Mapped[dict] = mapped_column(JSONB, nullable=False)
    effect: Mapped[PolicyEffect] = mapped_column(
        Enum(PolicyEffect, native_enum=False, length=20), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)


class CircuitBreaker(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "circuit_breakers"

    type: Mapped[BreakerType] = mapped_column(
        Enum(BreakerType, native_enum=False, length=20), nullable=False
    )
    threshold: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    state: Mapped[BreakerState] = mapped_column(
        Enum(BreakerState, native_enum=False, length=20),
        default=BreakerState.armed,
        nullable=False,
    )
    tripped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tripped_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
    )


class ReputationScore(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "reputation_scores"

    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    trust: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    accuracy: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    roi: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    reliability: Mapped[float] = mapped_column(Float, default=0.5, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class DecisionRequest(Base, PKMixin, TenantMixin, TimestampMixin):
    """The founder's action inbox. A pending request blocks its task."""

    __tablename__ = "decision_requests"

    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[DecisionKind] = mapped_column(
        Enum(DecisionKind, native_enum=False, length=30), nullable=False
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # The founder DM channel this decision is surfaced in. Every decision now
    # appears as a direct message to the founder marked "waiting for a response"
    # (see app.services.chat); this links the structured decision (which carries
    # the approval grant / budget metadata) to that chat thread so resolving it
    # can post back into the conversation. NULL for legacy rows.
    channel_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("chat_channels.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[DecisionStatus] = mapped_column(
        Enum(DecisionStatus, native_enum=False, length=20),
        default=DecisionStatus.pending,
        nullable=False,
        index=True,
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
