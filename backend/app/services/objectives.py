"""Objective progress: link objectives to delivered work, close the fulfilled ones.

Objectives (the mission's OKRs) carry no explicit task foreign key, so — like the
founder decision inbox does when it labels a decision with its related objective —
we link an objective to the tasks whose goals share the most distinctive words
with it. :func:`close_delivered_objectives` runs when a business cycle's run winds
down: any active objective whose matched work this cycle all succeeded is marked
``completed``, authoritatively and durably. That status is what the dashboard's
quest board reads to fire its "quest cleared" celebration.

The tokenizer here is the single source of truth for objective↔task keyword
linkage; ``app.api.decisions`` imports it so the inbox and the quest board agree
on what "related to this objective" means.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Objective, Task
from app.models.enums import TaskStatus

# Statuses that mean an objective is fulfilled — matches the client's quest board.
OBJECTIVE_ACTIVE = "active"
OBJECTIVE_COMPLETED = "completed"

# Minimum distinctive-word overlap for a task to count toward an objective. Two,
# so a single coincidental word never links unrelated work (mirrors the decision
# inbox's threshold).
_MIN_OVERLAP = 2

# Words too generic to signal which objective a task belongs to.
STOPWORDS = frozenset(
    """
    the and for with that this from your you our are will into them they then than
    have has had who what when where which while about over under above below
    company business mission objective objectives plan agent agents task work
    initiative initiatives founder approve approval budget spend decision goal
    """.split()
)


def keywords(*texts: str | None) -> set[str]:
    """Distinctive lowercase word tokens (≥4 chars, non-stopword) across ``texts``."""
    words: set[str] = set()
    for text in texts:
        for raw in (text or "").lower().replace("/", " ").split():
            token = "".join(ch for ch in raw if ch.isalnum())
            if len(token) >= 4 and token not in STOPWORDS:
                words.add(token)
    return words


def delivered_objective_ids(
    objectives: list[Objective],
    done_goals: list[str],
    failed_goals: list[str],
) -> list[uuid.UUID]:
    """Pure core: which active objectives were fully delivered this cycle.

    An objective is delivered when at least one completed task links to it and no
    *failed* task does — i.e. the work the fleet did toward it this cycle all
    landed. Kept database-free so the rule is unit-testable in isolation.
    """
    done_kw = [keywords(g) for g in done_goals]
    failed_kw = [keywords(g) for g in failed_goals]
    delivered: list[uuid.UUID] = []
    for obj in objectives:
        okw = keywords(obj.title, obj.rationale)
        if not okw:
            continue
        done_hits = sum(1 for kw in done_kw if len(kw & okw) >= _MIN_OVERLAP)
        failed_hits = sum(1 for kw in failed_kw if len(kw & okw) >= _MIN_OVERLAP)
        if done_hits >= 1 and failed_hits == 0:
            delivered.append(obj.id)
    return delivered


async def close_delivered_objectives(
    db: AsyncSession, *, company_id: uuid.UUID, root_run_id: uuid.UUID
) -> list[uuid.UUID]:
    """Mark every active objective fully delivered by this run as ``completed``.

    Called at cycle wind-down. Returns the ids of the objectives just closed (for
    logging/announcement); flushes but leaves the commit to the caller so it joins
    the same transaction that closes the run.
    """
    objectives = (
        await db.scalars(
            select(Objective).where(
                Objective.company_id == company_id,
                Objective.status == OBJECTIVE_ACTIVE,
            )
        )
    ).all()
    if not objectives:
        return []

    settled = (
        await db.scalars(
            select(Task).where(
                Task.root_run_id == root_run_id,
                Task.status.in_([TaskStatus.done, TaskStatus.failed]),
            )
        )
    ).all()
    done_goals = [t.goal for t in settled if t.status == TaskStatus.done]
    failed_goals = [t.goal for t in settled if t.status == TaskStatus.failed]
    if not done_goals:
        return []

    delivered = set(delivered_objective_ids(list(objectives), done_goals, failed_goals))
    closed: list[uuid.UUID] = []
    for obj in objectives:
        if obj.id in delivered:
            obj.status = OBJECTIVE_COMPLETED
            closed.append(obj.id)
    if closed:
        await db.flush()
    return closed
