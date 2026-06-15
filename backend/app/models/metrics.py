"""Real-world outcome signals — the feedback loop the agents read.

A :class:`MetricSignal` is one observed business datapoint (revenue, signups,
visits, conversion rate, …). Founders push them in via the metrics API, or an
integration records them; agents read recent signals back into context so they
reason about reality instead of acting blind. Append-only and tenant-scoped.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin
from app.models.enums import MetricSource


class MetricSignal(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "metric_signals"

    name: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source: Mapped[MetricSource] = mapped_column(
        Enum(MetricSource, native_enum=False, length=20),
        default=MetricSource.founder,
        nullable=False,
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
