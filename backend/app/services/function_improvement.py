"""The continuous per-function improvement cycle (RFC 0002, slice 3).

Closes the loop the founder asked for: GalaxiaOS owns keeping each function
improving, driven by the company's **real status** — not a generic retrospective.

Each cycle, for every function the company staffs, this reads which of the
function's ``health_signals`` (its KPIs, from ``function_catalog``) the company has
**actually measured** (real ``MetricSignal`` rows) versus which it is flying blind
on, and turns that into a concrete brief. The scheduled job (:mod:`app.jobs.
scheduled`) hands the brief to a CEO improvement run so the moves are dispatched
through the normal governed path (objective-tagged, budgeted, approval-gated).

The scoring is deliberately conservative and data-grounded: a KPI that has never
been measured is the highest-signal, unambiguous gap ("you can't improve what you
don't track"). Off-target/stalled detection against real targets is a follow-up
once targets are seeded (RFC §2 slice 2b), and slots into :func:`classify`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, MetricSignal
from app.services import function_catalog, function_health, function_metrics


@dataclass(frozen=True)
class FunctionStatus:
    """One function's health standing, derived from real signals."""

    agent_id: uuid.UUID
    function: str
    title: str
    measured: list[str] = field(default_factory=list)  # KPIs with real data
    unmeasured: list[str] = field(default_factory=list)  # KPIs never measured yet
    off_target: list[str] = field(default_factory=list)  # measured but below target

    @property
    def on_track(self) -> bool:
        """On track once every KPI is measured and none is below its target."""
        return not self.unmeasured and not self.off_target


def classify(
    health_signals: tuple[str, ...] | list[str],
    measured_names: set[str],
    *,
    latest_values: dict[str, float] | None = None,
    targets: dict[str, float] | None = None,
) -> dict:
    """Split a function's KPIs into measured / unmeasured / off-target (pure, tested).

    A KPI is *measured* once a real signal by that name exists; among the measured,
    one is *off-target* when it has a seeded target and its latest value is worse
    than that target — direction-aware, so ``bounce_rate`` above target counts as
    off. Database-free so the scoring rule stays unit-testable.
    """
    latest_values = latest_values or {}
    targets = targets or {}
    measured = [s for s in health_signals if s in measured_names]
    unmeasured = [s for s in health_signals if s not in measured_names]
    off_target = [
        s for s in measured
        if s in targets and s in latest_values
        and _below_target(s, latest_values[s], targets[s])
    ]
    return {"measured": measured, "unmeasured": unmeasured, "off_target": off_target}


def _below_target(name: str, value: float, target: float) -> bool:
    """Is ``value`` worse than ``target`` for this metric (direction-aware)?"""
    return value > target if function_metrics.is_lower_better(name) else value < target


async def _measured_signal_names(db: AsyncSession, company_id: uuid.UUID) -> set[str]:
    """Every distinct metric-signal name the company has ever recorded."""
    rows = await db.scalars(
        select(MetricSignal.name).where(MetricSignal.company_id == company_id).distinct()
    )
    return set(rows)


async def assess_functions(
    db: AsyncSession, *, company_id: uuid.UUID
) -> list[FunctionStatus]:
    """Assess every function the company staffs against its real health signals.

    Reads the function identity + KPIs off each agent's ``config`` (set at
    provisioning, RFC 0002 slice 2) and the company's recorded metric names, so the
    verdict is grounded in what actually happened — no LLM call. Core/oversight
    agents and non-catalog agents are skipped.
    """
    measured_names = await _measured_signal_names(db, company_id)
    targets = await function_health.kr_targets(db, company_id=company_id)
    latest = await function_health._latest_values(db, company_id, set(targets))
    agents = (
        await db.scalars(select(Agent).where(Agent.company_id == company_id))
    ).all()
    statuses: list[FunctionStatus] = []
    for agent in agents:
        cfg = agent.config or {}
        key = cfg.get("function")
        fn = function_catalog.get(key) if isinstance(key, str) else None
        if fn is None or fn.core:
            continue
        signals = tuple(cfg.get("health_signals") or fn.health_signals)
        split = classify(signals, measured_names, latest_values=latest, targets=targets)
        statuses.append(
            FunctionStatus(
                agent_id=agent.id,
                function=fn.key,
                title=fn.title,
                measured=split["measured"],
                unmeasured=split["unmeasured"],
                off_target=split["off_target"],
            )
        )
    return statuses


def improvement_brief(statuses: list[FunctionStatus]) -> str:
    """A CEO-facing brief naming what to improve per function, or "" if all on track.

    Empty when every function is at least measuring its KPIs — an empty brief means
    "nothing to drive this cycle", so the caller can skip spinning up a run.
    """
    off_track = [s for s in statuses if not s.on_track]
    if not off_track:
        return ""
    lines = [
        "Per-function health check (RFC 0002) — real status across the company. Drive "
        "the next improvement for each function below through its owning agent, tagging "
        "each initiative to the objective it advances:",
    ]
    for s in off_track:
        parts = []
        if s.unmeasured:
            parts.append(f"not yet tracking {', '.join(s.unmeasured)} (instrument + improve)")
        if s.off_target:
            parts.append(f"below target on {', '.join(s.off_target)} (act to close the gap)")
        lines.append(f"- {s.title} ({s.function}): {'; '.join(parts)}.")
    return "\n".join(lines)
