"""Circuit breakers — hard, non-advisory limits on the agent graph.

These bound recursion and runaway behaviour: task depth, tasks-per-run,
loop-signature repeats, and the company-level spend breaker. A tripped breaker
blocks the task; it is not config the agents can talk their way past.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import CircuitBreaker, Task
from app.models.enums import BreakerState, BreakerType, TaskStatus


@dataclass
class BreakerVerdict:
    ok: bool
    reason: str | None = None


def loop_signature(agent_id: uuid.UUID, goal: str) -> str:
    normalized = re.sub(r"\s+", " ", goal.strip().lower())
    return hashlib.sha256(f"{agent_id}:{normalized}".encode()).hexdigest()[:32]


async def _trip(
    db: AsyncSession,
    company_id: uuid.UUID,
    btype: BreakerType,
    reason: str,
    scope_agent_id: uuid.UUID | None = None,
) -> None:
    breaker = await db.scalar(
        select(CircuitBreaker).where(
            CircuitBreaker.company_id == company_id, CircuitBreaker.type == btype
        )
    )
    if breaker is None:
        breaker = CircuitBreaker(company_id=company_id, type=btype)
        db.add(breaker)
    breaker.state = BreakerState.tripped
    breaker.tripped_at = datetime.now(timezone.utc)
    breaker.tripped_reason = reason
    breaker.scope_agent_id = scope_agent_id
    await db.flush()


async def check_before_task(db: AsyncSession, task: Task) -> BreakerVerdict:
    """Run all pre-execution breaker checks for ``task``."""
    # Spend breaker already tripped → block.
    spend_breaker = await db.scalar(
        select(CircuitBreaker).where(
            CircuitBreaker.company_id == task.company_id,
            CircuitBreaker.type == BreakerType.spend,
            CircuitBreaker.state == BreakerState.tripped,
        )
    )
    if spend_breaker is not None:
        return BreakerVerdict(False, "spend circuit breaker tripped")

    # Depth cap.
    if task.depth > settings.max_task_depth:
        await _trip(db, task.company_id, BreakerType.loop, f"max depth {settings.max_task_depth}")
        return BreakerVerdict(False, "max task depth exceeded")

    # Tasks-per-run cap.
    run_count = await db.scalar(
        select(func.count(Task.id)).where(Task.root_run_id == task.root_run_id)
    )
    if (run_count or 0) > settings.max_tasks_per_run:
        await _trip(db, task.company_id, BreakerType.rate, "max tasks per run")
        return BreakerVerdict(False, "max tasks per run exceeded")

    # Loop-signature repeats within the run.
    if task.loop_signature:
        sig_count = await db.scalar(
            select(func.count(Task.id)).where(
                Task.root_run_id == task.root_run_id,
                Task.loop_signature == task.loop_signature,
            )
        )
        if (sig_count or 0) > settings.max_loop_signature_repeats:
            await _trip(
                db, task.company_id, BreakerType.loop, f"loop signature {task.loop_signature}"
            )
            return BreakerVerdict(False, "loop detected")

    return BreakerVerdict(True)


async def trip_spend_breaker(db: AsyncSession, company_id: uuid.UUID, reason: str) -> None:
    await _trip(db, company_id, BreakerType.spend, reason)


async def block_task(db: AsyncSession, task: Task, reason: str) -> None:
    task.status = TaskStatus.blocked
    task.output = {"blocked_reason": reason}
    await db.flush()
