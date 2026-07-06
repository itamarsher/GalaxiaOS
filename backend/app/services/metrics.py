"""Outcome signals — record and recall real-world business metrics.

This is the read side of the feedback loop: agents call :func:`latest_signals`
/ :func:`summarize_for_prompt` to ground their reasoning in observed results
instead of acting blind. Writes are append-only and tenant-scoped, and flow the
same way whether a founder, an agent tool, or an integration produced them.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MetricSignal
from app.models.enums import MetricSource


async def record_signal(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    name: str,
    value: float,
    unit: str | None = None,
    source: MetricSource = MetricSource.founder,
    note: str | None = None,
    structured: dict | None = None,
) -> MetricSignal:
    """Append one observed outcome signal for a company."""
    signal = MetricSignal(
        company_id=company_id,
        name=name[:120],
        value=value,
        unit=unit,
        source=source,
        note=note,
        structured=structured,
    )
    db.add(signal)
    await db.flush()
    return signal


async def latest_signals(
    db: AsyncSession, *, company_id: uuid.UUID, limit: int = 8
) -> list[MetricSignal]:
    """Most recent signals first (captured_at desc)."""
    rows = await db.scalars(
        select(MetricSignal)
        .where(MetricSignal.company_id == company_id)
        .order_by(MetricSignal.captured_at.desc())
        .limit(limit)
    )
    return list(rows)


def summarize_for_prompt(signals: list[MetricSignal]) -> str:
    """Compact, model-friendly rendering of recent signals for the agent loop."""
    if not signals:
        return (
            "No real-world metrics have been reported yet. Do not assume outcomes — "
            "act to acquire or measure them, and record results."
        )
    lines = []
    for s in signals:
        unit = f" {s.unit}" if s.unit else ""
        note = f" — {s.note}" if s.note else ""
        lines.append(f"- {s.name}: {s.value:g}{unit}{note}")
    return "Recent business metrics (most recent first):\n" + "\n".join(lines)
