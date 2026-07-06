"""Founder Copilot — daily board-level digests."""

from __future__ import annotations

from datetime import date

from sqlalchemy import Date, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin


class FounderDigest(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "founder_digests"

    period_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    highlights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    open_decisions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
