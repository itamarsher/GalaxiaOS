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
from datetime import UTC, datetime

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
    breaker.tripped_at = datetime.now(UTC)
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

    # Provider breaker tripped → block. The LLM credential is out of credit or
    # invalid; every task would fail the same way, so halt instead of burning the
    # run (and stacking silent failures). Cleared when the operator tops up / swaps
    # the key and explicitly resumes.
    provider_breaker = await db.scalar(
        select(CircuitBreaker).where(
            CircuitBreaker.company_id == task.company_id,
            CircuitBreaker.type == BreakerType.provider,
            CircuitBreaker.state == BreakerState.tripped,
        )
    )
    if provider_breaker is not None:
        return BreakerVerdict(False, "provider circuit breaker tripped")

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


async def trip_provider_breaker(db: AsyncSession, company_id: uuid.UUID, reason: str) -> None:
    """Halt the company because the LLM provider is unfunded/unauthorized.

    Idempotent: re-tripping an already-tripped breaker just refreshes its reason, so
    a repeated failure won't spam. Callers pair the first trip with a founder alert.
    """
    await _trip(db, company_id, BreakerType.provider, reason)


async def provider_breaker_reason(db: AsyncSession, company_id: uuid.UUID) -> str | None:
    """The reason a company is provider-blocked, or ``None`` when it isn't.

    Read by the run gate and the founder-facing snapshot so a provider halt is
    surfaced (escalated), not silent.
    """
    breaker = await db.scalar(
        select(CircuitBreaker).where(
            CircuitBreaker.company_id == company_id,
            CircuitBreaker.type == BreakerType.provider,
            CircuitBreaker.state == BreakerState.tripped,
        )
    )
    return breaker.tripped_reason or "provider blocked" if breaker is not None else None


async def clear_provider_breaker(db: AsyncSession, company_id: uuid.UUID) -> bool:
    """Re-arm the provider breaker after the operator addresses the funding/auth issue.

    Returns True if a tripped breaker was cleared. An explicit operator action (a
    fresh key, or a manual resume/run) means "I've fixed it, try again"; if the
    provider is still broken the next task simply re-trips and re-alerts.
    """
    breaker = await db.scalar(
        select(CircuitBreaker).where(
            CircuitBreaker.company_id == company_id,
            CircuitBreaker.type == BreakerType.provider,
            CircuitBreaker.state == BreakerState.tripped,
        )
    )
    if breaker is None:
        return False
    breaker.state = BreakerState.armed
    breaker.tripped_reason = None
    breaker.tripped_at = None
    await db.flush()
    return True


async def block_task(db: AsyncSession, task: Task, reason: str) -> None:
    task.status = TaskStatus.blocked
    task.output = {"blocked_reason": reason}
    task.transcript = None  # terminal: drop any working-memory checkpoint
    await db.flush()
