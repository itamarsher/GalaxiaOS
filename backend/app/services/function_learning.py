"""Cross-company function learning (RFC 0002, slice 4).

Slice 3 improves each function inside one company. This closes the loop *across*
companies: aggregate how each building block's real ``health_signals`` are moving
everywhere it runs, and feed the laggards' ``default_skills`` into the
skill-optimizer pipeline — so a playbook fix propagates to every company running
that function, and the shared starting point keeps getting better.

The data stays tenant-isolated; only the *learning* is shared. This reads across
companies (a platform-level, tenant-unset session, like the other platform crons)
and produces two pure, testable artifacts: which skills to prioritize
(:func:`priority_skills`) and a human/audit brief (:func:`learning_brief`).

Direction matters: a metric like ``bounce_rate`` improves when it *falls*. The
:data:`_LOWER_IS_BETTER` set encodes that, so "improved vs declined" is real rather
than naive delta sign. Everything the catalog defines a health signal for is
covered; a signal not listed defaults to higher-is-better.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, MetricSignal
from app.services import function_catalog, function_metrics


def trend(points: list[tuple[object, float]], *, lower_is_better: bool) -> str:
    """Classify a signal's movement over time (pure core, unit-tested).

    ``points`` is ``(captured_at, value)`` pairs (any order). Needs at least two to
    judge; returns ``"insufficient"`` otherwise. Compares the latest value to the
    earliest, honoring metric direction, → ``"improved"`` / ``"declined"`` / ``"flat"``.
    """
    if len(points) < 2:
        return "insufficient"
    ordered = sorted(points, key=lambda p: p[0])
    delta = ordered[-1][1] - ordered[0][1]
    if delta == 0:
        return "flat"
    rose = delta > 0
    improved = (not rose) if lower_is_better else rose
    return "improved" if improved else "declined"


@dataclass(frozen=True)
class FunctionPerformance:
    """How one building block is doing across every company that runs it."""

    function: str
    title: str
    default_skills: tuple[str, ...]
    adoption: int  # companies staffing this function
    measuring: int  # companies with real data on ≥1 of its health signals
    improved: int  # (company, signal) pairs trending up
    declined: int  # (company, signal) pairs trending down

    @property
    def lagging(self) -> bool:
        """A function worth prioritizing for a shared playbook fix.

        Two ways to lag across the platform: it's widely adopted but companies
        aren't even measuring its KPIs (the playbook isn't driving instrumentation),
        or, among those measuring, more signals are declining than improving.
        """
        if self.adoption == 0:
            return False
        under_measured = self.measuring * 2 < self.adoption  # <half are measuring
        declining = self.declined > self.improved
        return under_measured or declining


def priority_skills(
    perfs: list[FunctionPerformance], *, min_adoption: int = 1
) -> dict[str, str]:
    """Map each lagging function's skills → a cross-company reason (pure, tested).

    The skill-optimizer consumes this to prioritize playbooks by real business
    outcome across companies, not just per-company task-failure rate. A skill shared
    by several lagging functions keeps the first (most-adopted) reason.
    """
    out: dict[str, str] = {}
    for p in sorted(perfs, key=lambda p: -p.adoption):
        if p.adoption < min_adoption or not p.lagging:
            continue
        if p.measuring * 2 < p.adoption:
            reason = (
                f"'{p.title}' runs at {p.adoption} companies but only {p.measuring} "
                f"measure its KPIs — the playbook isn't driving instrumentation/outcomes."
            )
        else:
            reason = (
                f"'{p.title}' health is declining across companies "
                f"({p.declined} signals down vs {p.improved} up over the window)."
            )
        for skill in p.default_skills:
            out.setdefault(skill, reason)
    return out


async def aggregate(db: AsyncSession) -> list[FunctionPerformance]:
    """Aggregate per-function performance across all companies (RFC 0002 slice 4).

    Runs on a **tenant-unset** session so it can see every company (like the other
    platform crons); the underlying rows stay isolated — only the aggregate learning
    crosses the boundary. No LLM; pure real-signal math.
    """
    catalog = {f.key: f for f in function_catalog.selectable_functions()}
    signal_dirs = {
        s: function_metrics.is_lower_better(s)
        for f in catalog.values() for s in f.health_signals
    }
    if not signal_dirs:
        return []

    # company → the functions it staffs (from each agent's provisioned config).
    company_functions: dict[uuid.UUID, set[str]] = defaultdict(set)
    for agent in (await db.scalars(select(Agent))).all():
        key = (agent.config or {}).get("function")
        if key in catalog:
            company_functions[agent.company_id].add(key)

    # (company, signal) → its time-ordered value points, for the KPIs we track.
    points: dict[tuple[uuid.UUID, str], list[tuple[object, float]]] = defaultdict(list)
    rows = await db.execute(
        select(MetricSignal.company_id, MetricSignal.name, MetricSignal.captured_at,
               MetricSignal.value).where(MetricSignal.name.in_(signal_dirs.keys()))
    )
    for company_id, name, captured_at, value in rows:
        points[(company_id, name)].append((captured_at, value))

    perfs: list[FunctionPerformance] = []
    for key, fn in catalog.items():
        companies = [cid for cid, fns in company_functions.items() if key in fns]
        measuring = improved = declined = 0
        for cid in companies:
            measured_here = False
            for signal in fn.health_signals:
                pts = points.get((cid, signal))
                if not pts:
                    continue
                measured_here = True
                verdict = trend(pts, lower_is_better=signal_dirs[signal])
                if verdict == "improved":
                    improved += 1
                elif verdict == "declined":
                    declined += 1
            measuring += 1 if measured_here else 0
        if companies:
            perfs.append(FunctionPerformance(
                function=key, title=fn.title,
                default_skills=fn.default_skills,
                adoption=len(companies), measuring=measuring,
                improved=improved, declined=declined,
            ))
    return perfs


def winners(
    perfs: list[FunctionPerformance], *, min_adoption: int = 2
) -> list[FunctionPerformance]:
    """Functions improving broadly across companies — the *winners* to propagate.

    A winner is well-adopted, mostly measuring, and trending up more than down.
    ``min_adoption`` defaults to 2 so "across companies" is real, not one company's
    good week. Ordered most-improving first.
    """
    out = [
        p for p in perfs
        if p.adoption >= min_adoption
        and p.measuring * 2 >= p.adoption  # ≥half are measuring it
        and p.improved > p.declined
    ]
    return sorted(out, key=lambda p: (-(p.improved - p.declined), -p.adoption))


def winning_functions(perfs: list[FunctionPerformance], *, min_adoption: int = 2) -> set[str]:
    """Just the function keys that are winning across companies (RFC 0002 slice 4)."""
    return {p.function for p in winners(perfs, min_adoption=min_adoption)}


def reinforcement_note(function: str, perfs: list[FunctionPerformance]) -> str:
    """A one-line "this is working elsewhere — adopt it" note, or "" if not a winner.

    Handed to a company still off-track on a function that's a proven winner at other
    companies, so the improvement run reinforces what's working instead of
    reinventing — the propagation half of cross-company learning."""
    for p in winners(perfs):
        if p.function == function:
            return (
                f"'{p.title}' is a proven winner across companies "
                f"({p.improved} KPIs up vs {p.declined} down over {p.adoption} companies) — "
                f"adopt the shared playbook approach rather than starting from scratch."
            )
    return ""


def learning_brief(perfs: list[FunctionPerformance]) -> str:
    """A short audit line per function, laggards first (or "" if nothing to learn)."""
    ranked = sorted(perfs, key=lambda p: (not p.lagging, -p.adoption))
    lines = [
        f"- {p.title}: {p.adoption} companies, {p.measuring} measuring, "
        f"{p.improved}↑/{p.declined}↓"
        f"{'  ⚠ lagging' if p.lagging else ('  ★ winning' if p.improved > p.declined and p.adoption >= 2 else '')}"
        for p in ranked
    ]
    return "\n".join(lines)
