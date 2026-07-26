"""Auto-capture real health signals from the company's connected/internal data.

The improvement cycle (RFC 0002) is only as good as its measurements. Rather than
wait for an agent or the founder to hand-record a KPI, this derives the ones we
*already* have data for — from the CRM the fleet fills, and the runway the platform
computes — and records them as real `MetricSignal`s on the same pipeline, so the KR
board, assessment, and cross-company learning populate on their own.

Each **source** is best-effort and independent: it emits ``(name, value, unit)``
tuples only when its data is actually present (a company not using the CRM records
no CRM signals — no zero-noise), and a source that errors is logged and skipped, it
never breaks the others. Values that haven't changed since the last capture are
skipped so the time series stays meaningful and bounded.

Sources are pluggable — an analytics or Stripe-subscription source (website
visitors, MRR) slots in the same way once that data is connected.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CrmContact, CrmDeal, MetricSignal, RunwaySnapshot
from app.models.enums import CrmContactStatus, CrmDealStage, MetricSource
from app.observability import get_logger
from app.services import metrics as metrics_svc

_log = get_logger("abos.signal_capture")

_CAPTURE_WINDOW_DAYS = 30
_TERMINAL_STAGES = frozenset({CrmDealStage.won, CrmDealStage.lost})


async def _crm_signals(
    db: AsyncSession, company_id: uuid.UUID, since: datetime
) -> list[tuple[str, float, str]]:
    """inbound_leads (new lead contacts) + pipeline_created (open deal value)."""
    has_contacts = await db.scalar(
        select(CrmContact.id).where(CrmContact.company_id == company_id).limit(1)
    )
    out: list[tuple[str, float, str]] = []
    if has_contacts is not None:
        leads = await db.scalar(
            select(func.count()).select_from(CrmContact).where(
                CrmContact.company_id == company_id,
                CrmContact.status == CrmContactStatus.lead,
                CrmContact.created_at >= since,
            )
        )
        out.append(("inbound_leads", float(leads or 0), "leads/mo"))
    has_deals = await db.scalar(
        select(CrmDeal.id).where(CrmDeal.company_id == company_id).limit(1)
    )
    if has_deals is not None:
        pipeline_cents = await db.scalar(
            select(func.coalesce(func.sum(CrmDeal.amount_cents), 0)).where(
                CrmDeal.company_id == company_id,
                CrmDeal.created_at >= since,
                CrmDeal.stage.not_in(_TERMINAL_STAGES),
            )
        )
        out.append(("pipeline_created", (pipeline_cents or 0) / 100.0, "USD"))
    return out


async def _runway_signals(
    db: AsyncSession, company_id: uuid.UUID, since: datetime
) -> list[tuple[str, float, str]]:
    """runway_months + burn_rate from the latest computed runway snapshot."""
    snap = await db.scalar(
        select(RunwaySnapshot)
        .where(RunwaySnapshot.company_id == company_id)
        .order_by(RunwaySnapshot.computed_at.desc())
        .limit(1)
    )
    if snap is None:
        return []
    out: list[tuple[str, float, str]] = [
        ("burn_rate", round(snap.burn_rate_cents_per_day * 30 / 100.0, 2), "USD/mo"),
    ]
    if snap.projected_days_remaining is not None:
        out.append(("runway_months", round(snap.projected_days_remaining / 30.0, 2), "months"))
    return out


_SOURCES = (_crm_signals, _runway_signals)


async def capture(
    db: AsyncSession, *, company_id: uuid.UUID, window_days: int = _CAPTURE_WINDOW_DAYS
) -> dict[str, float]:
    """Record the health signals we can derive from connected data. Caller commits.

    Runs every source best-effort, skips values unchanged since the last capture,
    and returns the metrics actually written (name → value)."""
    since = datetime.now(UTC) - timedelta(days=max(1, window_days))
    candidates: list[tuple[str, float, str]] = []
    for source in _SOURCES:
        try:
            candidates.extend(await source(db, company_id, since))
        except Exception:  # noqa: BLE001 — one bad source must not break the others
            _log.exception(
                "signal_capture_source_failed",
                extra={"extra_fields": {"source": source.__name__, "company": str(company_id)}},
            )
    if not candidates:
        return {}

    latest = await _latest_values(db, company_id, {name for name, _, _ in candidates})
    recorded: dict[str, float] = {}
    for name, value, unit in candidates:
        if name in latest and abs(latest[name] - value) < 1e-9:
            continue  # unchanged — don't inflate the series
        await metrics_svc.record_signal(
            db, company_id=company_id, name=name, value=value, unit=unit,
            source=MetricSource.integration,
            note="Auto-captured from connected data (RFC 0002).",
        )
        recorded[name] = value
    return recorded


async def _latest_values(
    db: AsyncSession, company_id: uuid.UUID, names: set[str]
) -> dict[str, float]:
    rows = await db.execute(
        select(MetricSignal.name, MetricSignal.value, MetricSignal.captured_at)
        .where(MetricSignal.company_id == company_id, MetricSignal.name.in_(names))
        .order_by(MetricSignal.captured_at.desc())
    )
    out: dict[str, float] = {}
    for name, value, _ in rows:
        out.setdefault(name, value)
    return out
