"""Reputation scoring — per-agent trust/accuracy/ROI/reliability.

Updated incrementally as tasks complete (running mean per dimension). These
scores are the same signal a future agent marketplace would rank hired agents
by, so the model is reused rather than rebuilt.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ReputationScore


def _running_mean(old: float, sample: float, n: int) -> float:
    """Incremental mean folding ``sample`` into ``old`` after ``n`` prior samples."""
    return old + (sample - old) / (n + 1)


async def get_or_create(
    db: AsyncSession, *, company_id: uuid.UUID, agent_id: uuid.UUID
) -> ReputationScore:
    score = await db.scalar(
        select(ReputationScore).where(ReputationScore.agent_id == agent_id)
    )
    if score is None:
        score = ReputationScore(company_id=company_id, agent_id=agent_id)
        db.add(score)
        await db.flush()
    return score


async def record_task_outcome(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    agent_id: uuid.UUID,
    success: bool,
    blocked: bool = False,
    cost_cents: int = 0,
    value_signal: float | None = None,
) -> ReputationScore:
    """Fold one task outcome into the agent's reputation.

    Observations per dimension are in [0, 1]:
    - reliability: did the task complete at all (vs failed)?
    - accuracy:    did it produce a clean result (vs blocked/failed)?
    - roi:         value/cost proxy (defaults to a neutral prior when unknown).
    - trust:       composite of the three current values.
    """
    score = await get_or_create(db, company_id=company_id, agent_id=agent_id)
    n = score.sample_count

    reliability_obs = 1.0 if success else 0.0
    accuracy_obs = 1.0 if success else (0.3 if blocked else 0.0)
    if value_signal is not None:
        roi_obs = max(0.0, min(1.0, value_signal))
    else:
        roi_obs = 0.55 if (success and cost_cents <= 5000) else 0.45

    score.reliability = _running_mean(score.reliability, reliability_obs, n)
    score.accuracy = _running_mean(score.accuracy, accuracy_obs, n)
    score.roi = _running_mean(score.roi, roi_obs, n)
    score.trust = (score.reliability + score.accuracy + score.roi) / 3
    score.sample_count = n + 1
    await db.flush()
    return score
