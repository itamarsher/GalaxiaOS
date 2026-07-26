"""Formal health KRs + agent-based metrics for functions (RFC 0002).

Slice 2 kept a function's health target on the agent (its prompt). This makes it
**formal**: each function's `health_signals` become real `KeyResult` rows under a
dedicated "Operational health" objective, so targets are first-class — the founder
can set them, the dashboard shows them, and the improvement cycle can detect
*off-target* (not just *unmeasured*).

Two kinds of KR are seeded (RFC 0002):

- **Business KPIs** — per function, from the catalog (`signup_conversion_rate`, …).
- **Agent-based KPIs** — company-level, from the reputation model
  (`agent_reliability`/`agent_trust`/`agent_roi`), so the scorecard also tracks
  whether the agents *running* the functions are dependable. `record_agent_signals`
  derives them from `ReputationScore` and records them as real `MetricSignal`s.

Kept idempotent: re-running reconciles KRs to the current function set (adds new
picks' KPIs, prunes a removed function's) — safe to call after every provision.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Company, KeyResult, MetricSignal, Mission, Objective, ReputationScore
from app.models.enums import MetricSource
from app.services import function_catalog, function_metrics
from app.services import metrics as metrics_svc

#: The dedicated objective the health KRs hang under. Sorted last (high priority
#: number) so it never displaces the founder's mission objectives.
HEALTH_OBJECTIVE_TITLE = "Operational health"
_HEALTH_OBJECTIVE_PRIORITY = 999


def _desired_metrics(function_keys: set[str]) -> list[str]:
    """The KR metrics for a set of functions: their business KPIs + agent KPIs."""
    metrics: list[str] = []
    for key in function_keys:
        fn = function_catalog.get(key)
        if fn is not None:
            metrics.extend(fn.health_signals)
    metrics.extend(function_metrics.AGENT_SIGNALS)
    # Dedupe, preserve order.
    seen: set[str] = set()
    return [m for m in metrics if not (m in seen or seen.add(m))]


async def _health_objective(db: AsyncSession, company: Company) -> Objective | None:
    """Get or create the company's "Operational health" objective (needs a mission)."""
    obj = await db.scalar(
        select(Objective).where(
            Objective.company_id == company.id,
            Objective.title == HEALTH_OBJECTIVE_TITLE,
        )
    )
    if obj is not None:
        return obj
    mission = await db.scalar(select(Mission).where(Mission.company_id == company.id))
    if mission is None:
        return None
    obj = Objective(
        company_id=company.id,
        mission_id=mission.id,
        title=HEALTH_OBJECTIVE_TITLE,
        rationale="Keep every function measuring and hitting its health KPIs (RFC 0002).",
        priority=_HEALTH_OBJECTIVE_PRIORITY,
    )
    db.add(obj)
    await db.flush()
    return obj


async def sync_health_krs(db: AsyncSession, *, company: Company) -> int:
    """Reconcile the company's health KRs to its current functions. Returns KR count.

    Adds a KR for each business KPI of every staffed function plus the agent-based
    KPIs, prunes KRs for functions no longer staffed, and leaves existing targets
    (which the founder may have tuned) untouched. Idempotent; caller commits.
    """
    agents = (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()
    function_keys = {
        k for a in agents
        if isinstance(k := (a.config or {}).get("function"), str)
        and (fn := function_catalog.get(k)) is not None and not fn.core
    }
    desired = _desired_metrics(function_keys)
    obj = await _health_objective(db, company)
    if obj is None:
        return 0

    existing = {
        kr.metric: kr
        for kr in (
            await db.scalars(select(KeyResult).where(KeyResult.objective_id == obj.id))
        ).all()
    }
    desired_set = set(desired)
    for metric, kr in existing.items():
        if metric not in desired_set:
            await db.delete(kr)  # a function was dropped — retire its KR
    for metric in desired:
        if metric in existing:
            continue
        db.add(KeyResult(
            company_id=company.id,
            objective_id=obj.id,
            metric=metric,
            unit=function_metrics.signal_unit(metric),
            target_value=function_metrics.default_target(metric),
        ))
    await db.flush()
    return len(desired)


async def kr_targets(db: AsyncSession, *, company_id: uuid.UUID) -> dict[str, float]:
    """Metric → target for the company's health KRs that have a target set."""
    rows = await db.execute(
        select(KeyResult.metric, KeyResult.target_value)
        .join(Objective, Objective.id == KeyResult.objective_id)
        .where(
            KeyResult.company_id == company_id,
            Objective.title == HEALTH_OBJECTIVE_TITLE,
            KeyResult.target_value.is_not(None),
        )
    )
    return {metric: target for metric, target in rows}


async def refresh_kr_values(db: AsyncSession, *, company_id: uuid.UUID) -> None:
    """Update each health KR's ``current_value`` to the latest matching signal.

    Keeps the formal KR board in sync with reality so the founder/dashboard sees
    live progress. Caller commits."""
    krs = (
        await db.scalars(
            select(KeyResult)
            .join(Objective, Objective.id == KeyResult.objective_id)
            .where(
                KeyResult.company_id == company_id,
                Objective.title == HEALTH_OBJECTIVE_TITLE,
            )
        )
    ).all()
    if not krs:
        return
    latest = await _latest_values(db, company_id, {kr.metric for kr in krs})
    for kr in krs:
        if kr.metric in latest:
            kr.current_value = latest[kr.metric]
    await db.flush()


async def _latest_values(
    db: AsyncSession, company_id: uuid.UUID, names: set[str]
) -> dict[str, float]:
    """Most-recent value per signal name for a company (empty for never-measured)."""
    if not names:
        return {}
    rows = await db.execute(
        select(MetricSignal.name, MetricSignal.value, MetricSignal.captured_at)
        .where(MetricSignal.company_id == company_id, MetricSignal.name.in_(names))
        .order_by(MetricSignal.captured_at.desc())
    )
    out: dict[str, float] = {}
    for name, value, _ in rows:
        out.setdefault(name, value)  # first seen = latest (desc order)
    return out


async def record_agent_signals(db: AsyncSession, *, company_id: uuid.UUID) -> bool:
    """Record company-level agent-based KPIs from the reputation model (RFC 0002).

    Averages the per-agent reputation dimensions (only agents with real samples) and
    writes them as `MetricSignal`s so the agent-operating health flows through the
    same measurement pipeline as business KPIs. No-ops (returns False) until agents
    have accrued reputation. Caller commits.
    """
    scores = (
        await db.scalars(
            select(ReputationScore).where(
                ReputationScore.company_id == company_id,
                ReputationScore.sample_count > 0,
            )
        )
    ).all()
    if not scores:
        return False
    n = len(scores)
    for name, value in (
        ("agent_reliability", sum(s.reliability for s in scores) / n),
        ("agent_trust", sum(s.trust for s in scores) / n),
        ("agent_roi", sum(s.roi for s in scores) / n),
    ):
        await metrics_svc.record_signal(
            db, company_id=company_id, name=name, value=round(value, 4),
            unit="score", source=MetricSource.agent,
            note="Company-average agent reputation (RFC 0002).",
        )
    return True
