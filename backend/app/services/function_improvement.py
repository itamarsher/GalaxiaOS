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
from app.services import function_catalog


@dataclass(frozen=True)
class FunctionStatus:
    """One function's health standing, derived from real signals."""

    agent_id: uuid.UUID
    function: str
    title: str
    measured: list[str] = field(default_factory=list)  # KPIs with real data
    unmeasured: list[str] = field(default_factory=list)  # KPIs never measured yet

    @property
    def on_track(self) -> bool:
        """A function is on track (for now) once every KPI is at least measured."""
        return not self.unmeasured


def classify(health_signals: tuple[str, ...] | list[str], measured_names: set[str]) -> dict:
    """Split a function's KPIs into measured vs unmeasured (pure core, unit-tested).

    A KPI counts as measured once a real signal by that name has been recorded.
    Kept database-free so the scoring rule is testable in isolation and is the seam
    where off-target detection is added once KPI targets exist.
    """
    measured = [s for s in health_signals if s in measured_names]
    unmeasured = [s for s in health_signals if s not in measured_names]
    return {"measured": measured, "unmeasured": unmeasured}


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
        split = classify(signals, measured_names)
        statuses.append(
            FunctionStatus(
                agent_id=agent.id,
                function=fn.key,
                title=fn.title,
                measured=split["measured"],
                unmeasured=split["unmeasured"],
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
        gap = ", ".join(s.unmeasured)
        lines.append(
            f"- {s.title} ({s.function}): not yet tracking {gap}. Instrument "
            f"{'these KPIs' if len(s.unmeasured) > 1 else 'this KPI'} (record real "
            f"signals), then act to improve {'them' if len(s.unmeasured) > 1 else 'it'}."
        )
    return "\n".join(lines)
