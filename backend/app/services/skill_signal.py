"""Skill reward signal — turn skill-usage telemetry into a per-skill scorecard.

The skill optimizer needs to know *which* playbooks are underperforming before it
spends a model call trying to improve one. That signal is assembled here from two
durable sources that survive a task's terminal transcript drop:

- :class:`~app.models.skill_usage.SkillUsage` — the "which skill did this task
  load" rows written at the ``load_skill`` chokepoint, and
- :class:`~app.models.run.Task` — the task's terminal ``status`` (done vs
  failed/blocked) and its ``output`` summary/error.

For each skill we compute a success rate over the tasks that used it in a recent
window, plus a few concrete failure examples (goal + error/summary) the optimizer
feeds to the model as evidence of what to fix. :func:`rank_candidates` orders the
worst offenders first (low success rate, enough samples to trust it, more traffic
breaking ties) so a bounded per-tick batch spends its budget where it matters.

Everything here is read-only aggregation except :func:`record_usage`, the
best-effort writer the tool layer calls; it never raises into the tool call.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TaskStatus
from app.models.run import Task
from app.models.skill_usage import SkillUsage
from app.observability import get_logger

_log = get_logger("abos.skill_signal")

#: Terminal statuses that count as a success / a failure for a skill's tasks.
#: Non-terminal tasks (queued/running/waiting/auditing) don't count either way.
_SUCCESS = {TaskStatus.done}
_FAILURE = {TaskStatus.failed, TaskStatus.blocked}

#: Cap on how many failure examples we carry per skill (keeps the optimizer prompt
#: bounded) and how long each example's detail may be.
_MAX_FAILURES = 5
_MAX_DETAIL_CHARS = 400


async def record_usage(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    task_id: uuid.UUID | None,
    agent_id: uuid.UUID | None,
    skill_name: str,
) -> None:
    """Record one ``load_skill`` call (best-effort, SAVEPOINT-isolated).

    Joins the caller's (already tenant-scoped) transaction and is isolated in a
    SAVEPOINT so a telemetry failure rolls back only this row, never the tool call
    it rides on — same discipline as :mod:`app.services.event_counters`.
    """
    name = (skill_name or "").strip()
    if not name:
        return
    try:
        async with db.begin_nested():
            db.add(
                SkillUsage(
                    company_id=company_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    skill_name=name,
                )
            )
    except Exception:  # noqa: BLE001 — telemetry must never break the tool call
        _log.exception("skill_usage_record_failed", extra={"extra_fields": {"skill": name}})


@dataclass(frozen=True)
class FailureExample:
    """One failing task that used the skill — evidence for the optimizer."""

    goal: str
    detail: str  # the task's error, else its result summary


@dataclass(frozen=True)
class SkillSignal:
    """A skill's recent outcome scorecard across the tasks that loaded it."""

    skill_name: str
    sample_count: int  # terminal tasks that used the skill in the window
    success_count: int
    failure_count: int
    failures: list[FailureExample] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Fraction of terminal tasks that succeeded (1.0 when there are none)."""
        return self.success_count / self.sample_count if self.sample_count else 1.0


def _detail_of(status: TaskStatus, output: dict | None) -> str:
    data = output or {}
    if status in _FAILURE:
        detail = str(data.get("error") or data.get("summary") or "").strip()
    else:
        detail = str(data.get("summary") or "").strip()
    return detail[:_MAX_DETAIL_CHARS]


async def collect(
    db: AsyncSession, *, company_id: uuid.UUID, window_days: int
) -> dict[str, SkillSignal]:
    """Aggregate a per-skill :class:`SkillSignal` for one company over a window.

    One task counts once per skill even if it loaded that skill twice. Only
    terminal tasks contribute to the counts; failures also seed the examples.
    """
    since = datetime.now(UTC) - timedelta(days=max(1, window_days))
    rows = (
        await db.execute(
            select(
                SkillUsage.skill_name,
                SkillUsage.task_id,
                Task.status,
                Task.goal,
                Task.output,
            )
            .join(Task, Task.id == SkillUsage.task_id)
            .where(
                SkillUsage.company_id == company_id,
                SkillUsage.created_at >= since,
            )
        )
    ).all()

    # Dedupe to one (skill, task) pair — a task that loaded a skill twice is one
    # sample — and keep each task's terminal status/output for scoring.
    per_skill: dict[str, dict[uuid.UUID, tuple[TaskStatus, str, dict | None]]] = {}
    for skill_name, task_id, status, goal, output in rows:
        if task_id is None or status not in (_SUCCESS | _FAILURE):
            continue
        per_skill.setdefault(skill_name, {})[task_id] = (status, goal or "", output)

    signals: dict[str, SkillSignal] = {}
    for skill_name, tasks in per_skill.items():
        success = failure = 0
        failures: list[FailureExample] = []
        for status, goal, output in tasks.values():
            if status in _SUCCESS:
                success += 1
            else:
                failure += 1
                if len(failures) < _MAX_FAILURES:
                    failures.append(
                        FailureExample(
                            goal=goal[:_MAX_DETAIL_CHARS], detail=_detail_of(status, output)
                        )
                    )
        signals[skill_name] = SkillSignal(
            skill_name=skill_name,
            sample_count=success + failure,
            success_count=success,
            failure_count=failure,
            failures=failures,
        )
    return signals


def rank_candidates(
    signals: dict[str, SkillSignal],
    *,
    min_samples: int,
    success_ceiling: float,
) -> list[SkillSignal]:
    """Worst-performing skills first: the ones worth spending an optimizer call on.

    Keeps only skills with at least ``min_samples`` terminal tasks (so a single bad
    run can't trigger a rewrite) and a success rate at or below ``success_ceiling``
    (leave the skills that are already working alone). Orders by success rate
    ascending, breaking ties by sample count descending — fix the most-used broken
    playbooks first.
    """
    eligible = [
        s
        for s in signals.values()
        if s.sample_count >= min_samples and s.success_rate <= success_ceiling
    ]
    return sorted(eligible, key=lambda s: (s.success_rate, -s.sample_count))
