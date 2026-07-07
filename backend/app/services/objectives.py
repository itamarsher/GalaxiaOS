"""Objective progress: close the objectives the fleet actually delivered.

Every task carries an explicit ``objective_id`` — the CEO tags each dispatched
initiative with the objective it serves and sub-tasks inherit it (see
``app.runtime.tools.core``). So completion is a direct roll-up, not a guess:
:func:`close_delivered_objectives` runs when a business cycle's run winds down and
marks ``completed`` any active objective whose tagged work this cycle all
succeeded. That status is what the dashboard's quest board reads to fire its
"quest cleared" celebration.

This module also owns the small helpers the CEO needs to reference objectives by a
stable 1-based handle when dispatching: :func:`ordered_objectives` (the canonical
priority order) and :func:`resolve_objective_id` (handle → id).
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


async def ordered_objectives(
    db: AsyncSession, company_id: uuid.UUID
) -> list[Objective]:
    """The company's objectives in the canonical order (priority asc, then id).

    The CEO references objectives by their 1-based position in this list, so both
    the prompt that lists them and :func:`resolve_objective_id` must use the same
    ordering — hence one place that defines it.
    """
    return list(
        (
            await db.scalars(
                select(Objective)
                .where(Objective.company_id == company_id)
                .order_by(Objective.priority, Objective.id)
            )
        ).all()
    )


async def has_objectives(db: AsyncSession, company_id: uuid.UUID) -> bool:
    """Whether the company has any objectives at all.

    Lets the dispatch gate stay quiet for a company with none yet (nothing to tag)
    while still requiring a tag once objectives exist.
    """
    return (
        await db.scalar(
            select(Objective.id).where(Objective.company_id == company_id).limit(1)
        )
    ) is not None


async def resolve_objective_id(
    db: AsyncSession, company_id: uuid.UUID, handle: object
) -> uuid.UUID | None:
    """Map a CEO-supplied 1-based objective handle to an objective id, or None.

    Accepts an int or a numeric string (what an LLM tends to emit). Out-of-range
    or non-numeric handles resolve to None — the task simply goes untagged rather
    than erroring, so a stray value never breaks a dispatch.
    """
    if handle is None:
        return None
    try:
        idx = int(handle)
    except (TypeError, ValueError):
        return None
    if idx < 1:
        return None
    objectives = await ordered_objectives(db, company_id)
    if idx > len(objectives):
        return None
    return objectives[idx - 1].id


def objectives_prompt_block(objectives: list[Objective]) -> str:
    """A numbered objectives list for the agent prompt, or "" when there are none.

    The number is the handle the CEO passes as ``objective`` to ``dispatch_task``,
    so a dispatched initiative links to the objective it advances.
    """
    if not objectives:
        return ""
    lines = [f"  {i + 1}. {o.title}" for i, o in enumerate(objectives)]
    return (
        "Company objectives (when you dispatch an initiative, set `objective` to the "
        "number of the objective it advances so progress is tracked):\n"
        + "\n".join(lines)
    )


def delivered_objective_ids(
    objective_ids: list[uuid.UUID],
    done_objective_ids: list[uuid.UUID | None],
    failed_objective_ids: list[uuid.UUID | None],
) -> list[uuid.UUID]:
    """Pure core: which active objectives were fully delivered this cycle.

    An objective is delivered when at least one completed task is tagged with it
    and no *failed* task is — i.e. the work the fleet did toward it this cycle all
    landed. Kept database-free so the rule is unit-testable in isolation.
    """
    done = {oid for oid in done_objective_ids if oid is not None}
    failed = {oid for oid in failed_objective_ids if oid is not None}
    return [oid for oid in objective_ids if oid in done and oid not in failed]


async def close_delivered_objectives(
    db: AsyncSession, *, company_id: uuid.UUID, root_run_id: uuid.UUID
) -> list[uuid.UUID]:
    """Mark every active objective fully delivered by this run as ``completed``.

    Called at cycle wind-down. Returns the ids of the objectives just closed (for
    logging); flushes but leaves the commit to the caller so it joins the same
    transaction that closes the run.
    """
    active = (
        await db.scalars(
            select(Objective.id).where(
                Objective.company_id == company_id,
                Objective.status == OBJECTIVE_ACTIVE,
            )
        )
    ).all()
    if not active:
        return []

    settled = (
        await db.execute(
            select(Task.objective_id, Task.status).where(
                Task.root_run_id == root_run_id,
                Task.objective_id.is_not(None),
                Task.status.in_([TaskStatus.done, TaskStatus.failed]),
            )
        )
    ).all()
    done_ids = [oid for oid, status in settled if status == TaskStatus.done]
    failed_ids = [oid for oid, status in settled if status == TaskStatus.failed]
    if not done_ids:
        return []

    delivered = set(delivered_objective_ids(list(active), done_ids, failed_ids))
    if not delivered:
        return []
    objectives = (
        await db.scalars(
            select(Objective).where(Objective.id.in_(delivered))
        )
    ).all()
    closed: list[uuid.UUID] = []
    for obj in objectives:
        obj.status = OBJECTIVE_COMPLETED
        closed.append(obj.id)
    if closed:
        await db.flush()
    return closed
