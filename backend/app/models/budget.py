"""Budget OS — the unified money ledger.

``spend_entries`` is the single source of truth for *all* spend (LLM or
otherwise). ``llm_calls`` and ``external_charges`` are per-category detail rows
that reference a spend entry. ``budgets.spent_cents`` / ``reserved_cents`` are
materialised aggregates locked ``FOR UPDATE`` on every reservation.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import BudgetPeriod, SpendCategory


class Budget(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "budgets"

    period: Mapped[BudgetPeriod] = mapped_column(
        Enum(BudgetPeriod, native_enum=False, length=20),
        default=BudgetPeriod.monthly,
        nullable=False,
    )
    limit_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    spent_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    # Optimistic-lock version (bumped on each reserve/commit alongside FOR UPDATE).
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class SpendEntry(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "spend_entries"

    budget_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category: Mapped[SpendCategory] = mapped_column(
        Enum(SpendCategory, native_enum=False, length=20), nullable=False, index=True
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    reserved_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)


class LLMCall(Base, PKMixin, TenantMixin, TimestampMixin):
    """Token-level detail for an ``llm`` spend entry."""

    __tablename__ = "llm_calls"

    spend_entry_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("spend_entries.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class ExternalCharge(Base, PKMixin, TenantMixin, TimestampMixin):
    """Detail for an ``external`` spend entry (e.g. a domain purchase)."""

    __tablename__ = "external_charges"

    spend_entry_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("spend_entries.id", ondelete="CASCADE"), nullable=False
    )
    vendor: Mapped[str] = mapped_column(String(120), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(120), nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class RunwaySnapshot(Base, PKMixin, TenantMixin):
    __tablename__ = "runway_snapshots"

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    balance_cents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    burn_rate_cents_per_day: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    projected_days_remaining: Mapped[float | None] = mapped_column(Float, nullable=True)
