"""Reliability monitor: turn Galaxia's own failed tasks into bug reports.

Closes the operational half of the dogfooding loop. When one of Galaxia's agent
tasks fails, this finds it and wakes the Platform agent to investigate — read the
code, check the Render deploys/logs when it looks infrastructure-related — and
file a ``report_bug``, which flows through the promoter → tracker issue → Claude
Code auto-fix pipeline. Each failed task is reviewed exactly once, marked by
``Task.reliability_reviewed_at``.

The batch logic lives here (takes a session, testable); a cron in
:mod:`app.jobs.scheduled` calls it on Galaxia's behalf and enqueues the
investigation tasks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Task
from app.models.enums import TaskStatus
from app.runtime import orchestrator


async def review_failed_tasks(
    db: AsyncSession, *, company_id: uuid.UUID, limit: int
) -> dict:
    """Investigate up to ``limit`` new failed tasks; returns ids to enqueue.

    Picks failed tasks not yet reviewed (oldest first), creates a Platform-agent
    investigation task for each, and marks the failure reviewed. Stops early if
    there is no Platform agent (leaves the rest for a later tick). The caller
    commits and enqueues ``review_task_ids``.
    """
    failed = (
        await db.scalars(
            select(Task)
            .where(
                Task.company_id == company_id,
                Task.status == TaskStatus.failed,
                Task.reliability_reviewed_at.is_(None),
            )
            .order_by(Task.created_at.asc())
            .limit(limit)
        )
    ).all()

    review_task_ids: list[uuid.UUID] = []
    for ft in failed:
        tid = await orchestrator.create_reliability_review_task(
            db, company_id, failed_task=ft
        )
        if tid is None:
            break  # no Platform agent yet — leave unmarked for a later tick
        ft.reliability_reviewed_at = datetime.now(UTC)
        review_task_ids.append(tid)

    await db.flush()
    return {"reviewed": len(review_task_ids), "review_task_ids": review_task_ids}
