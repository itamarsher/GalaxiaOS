"""Runway forecasting and ROI-based pausing (FR-10, FR-11).

Burn rate is the trailing-7-day spend per day; runway is balance / burn. When
runway drops below the alert threshold we raise a founder decision request
(deduped) rather than silently changing strategy. Low-ROI pausing is exposed as
an explicit, founder-triggerable action (also reachable via the NL command plane).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Agent,
    Budget,
    DecisionRequest,
    ReputationScore,
    RunwaySnapshot,
    SpendEntry,
)
from app.models.enums import AgentStatus, DecisionKind, DecisionStatus


async def recompute(db: AsyncSession, company_id: uuid.UUID) -> RunwaySnapshot | None:
    budget = await db.scalar(select(Budget).where(Budget.company_id == company_id).limit(1))
    if budget is None:
        return None

    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    trailing = await db.scalar(
        select(func.coalesce(func.sum(SpendEntry.amount_cents), 0)).where(
            SpendEntry.company_id == company_id, SpendEntry.created_at >= cutoff
        )
    )
    burn_per_day = int((trailing or 0) / 7)
    balance = max(0, budget.limit_cents - budget.spent_cents)
    projected_days = (balance / burn_per_day) if burn_per_day > 0 else None

    snapshot = RunwaySnapshot(
        company_id=company_id,
        balance_cents=balance,
        burn_rate_cents_per_day=burn_per_day,
        projected_days_remaining=projected_days,
    )
    db.add(snapshot)
    await db.flush()

    if projected_days is not None and projected_days < settings.runway_alert_days:
        await _raise_runway_alert(db, company_id, projected_days)
    return snapshot


async def _raise_runway_alert(db: AsyncSession, company_id: uuid.UUID, days: float) -> None:
    existing = await db.scalar(
        select(DecisionRequest).where(
            DecisionRequest.company_id == company_id,
            DecisionRequest.kind == DecisionKind.strategy,
            DecisionRequest.status == DecisionStatus.pending,
            DecisionRequest.summary.like("Runway low%"),
        )
    )
    if existing is not None:
        return
    db.add(
        DecisionRequest(
            company_id=company_id,
            kind=DecisionKind.strategy,
            summary=f"Runway low: ~{days:.0f} days remaining. Top up budget or pause low-ROI agents?",
            payload={"projected_days_remaining": days, "suggested_action": "pause_low_roi"},
            status=DecisionStatus.pending,
        )
    )
    await db.flush()


async def pause_low_roi_agents(
    db: AsyncSession, company_id: uuid.UUID, roi_threshold: float | None = None
) -> list[uuid.UUID]:
    """Pause active agents whose reputation ROI is below the threshold."""
    threshold = settings.roi_pause_floor if roi_threshold is None else roi_threshold
    rows = await db.execute(
        select(Agent, ReputationScore)
        .join(ReputationScore, ReputationScore.agent_id == Agent.id)
        .where(
            Agent.company_id == company_id,
            Agent.status == AgentStatus.active,
            ReputationScore.sample_count > 0,
            ReputationScore.roi < threshold,
        )
    )
    paused: list[uuid.UUID] = []
    for agent, _score in rows.all():
        agent.status = AgentStatus.paused
        paused.append(agent.id)
    await db.flush()
    return paused
