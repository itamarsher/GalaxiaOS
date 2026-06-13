"""Mission → Objectives → Key Results (the company objective tree)."""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin


class Mission(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "missions"

    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_model_assumptions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    target_market: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    constraints: Mapped[list | None] = mapped_column(JSONB, nullable=True)


class Objective(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "objectives"

    mission_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("missions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)


class KeyResult(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "key_results"

    objective_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("objectives.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric: Mapped[str] = mapped_column(String(255), nullable=False)
    target_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="active", nullable=False)
