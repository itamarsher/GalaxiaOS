"""Per-company event counters — a running tally of everything the system does.

One row per ``(company_id, event_type)`` holding a monotonic ``count`` and the
timestamp of the most recent event. The runtime increments these at its natural
chokepoints (an LLM completion, a tool call, a task starting/finishing, a
decision escalated to the founder, an outbound message, …) so the totals are a
cheap, always-available summary of a company's activity without scanning the
detail tables (tasks, spend entries, external messages).

The numbers back the dashboard's live stats and are a useful primitive going
forward — usage metering, anomaly detection, rate/health signals, billing
context. Incrementing is best-effort and isolated in a SAVEPOINT by the service
layer, so a counter write can never break the business transaction it rides on.

Tenant-scoped and RLS-protected like every other business table.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin


class EventCounter(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "event_counters"
    __table_args__ = (
        UniqueConstraint("company_id", "event_type", name="uq_event_counters_company_type"),
    )

    #: The event kind being counted (see :class:`app.models.enums.EventType`).
    #: Stored as a plain string so new event types never require a schema change.
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    #: Monotonic total of this event for this company.
    count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: When the most recent event of this type was recorded.
    last_event_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
