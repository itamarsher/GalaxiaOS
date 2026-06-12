"""Agents and the communication topology (org chart).

Marketplace columns (``backend_type``, ``source``, ``marketplace_listing_id``,
``invocation_price_cents``) are nullable and unused at MVP — they exist so a
future *hired* agent slots into this same table without a migration.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import (
    AgentBackendType,
    AgentRole,
    AgentSource,
    AgentStatus,
    AutonomyLevel,
    EdgeRelation,
)


class Agent(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "agents"

    role: Mapped[AgentRole] = mapped_column(
        Enum(AgentRole, native_enum=False, length=20), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    autonomy_level: Mapped[AutonomyLevel] = mapped_column(
        Enum(AutonomyLevel, native_enum=False, length=20),
        default=AutonomyLevel.approve_required,
        nullable=False,
    )
    status: Mapped[AgentStatus] = mapped_column(
        Enum(AgentStatus, native_enum=False, length=20), default=AgentStatus.active, nullable=False
    )
    model_pref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    monthly_budget_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reports_to_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # ── Backend / marketplace seams (MVP: native/generated; rest reserved) ──
    backend_type: Mapped[AgentBackendType] = mapped_column(
        Enum(AgentBackendType, native_enum=False, length=20),
        default=AgentBackendType.native,
        nullable=False,
    )
    source: Mapped[AgentSource] = mapped_column(
        Enum(AgentSource, native_enum=False, length=20),
        default=AgentSource.generated,
        nullable=False,
    )
    marketplace_listing_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    invocation_price_cents: Mapped[int | None] = mapped_column(Integer, nullable=True)


class AgentEdge(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "agent_edges"

    from_agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    to_agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[EdgeRelation] = mapped_column(
        Enum(EdgeRelation, native_enum=False, length=20),
        default=EdgeRelation.reports_to,
        nullable=False,
    )
