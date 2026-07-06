"""On-demand business-cycle control — the game's "advance a round" primitive.

A business cycle is normally driven by the daily ``run_business_cycle`` cron
(``app/jobs/scheduled.py``) plus continuous auto-chaining
(``orchestrator._maybe_continue_cycle``). The game's "Advance cycle" button needs
to kick exactly one cycle for one company on demand, with the same guards the
cron uses so it never stacks a second run on top of a live one or spends past the
budget floor.

``start_cycle`` mirrors the cron body for a single company and returns the CEO
root task id for the caller to enqueue (kept out of the service so it stays a
pure DB operation that tests can drive directly). ``cycle_status`` reports whether
a cycle is in progress and whether a new one can start, so the UI can render the
button state and recover on load.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import CircuitBreaker, Company, Task
from app.models.enums import BreakerState, BreakerType, CompanyStatus
from app.runtime import orchestrator
from app.services import budget as budget_svc


class CycleStart:
    """Result of a start_cycle attempt (plain object; the route maps to a schema)."""

    def __init__(
        self,
        *,
        started: bool,
        reason: str,
        active: bool,
        task_id: uuid.UUID | None = None,
    ) -> None:
        self.started = started
        self.reason = reason
        self.active = active
        self.task_id = task_id


class CycleStatus:
    def __init__(self, *, active: bool, can_start: bool, reason: str, active_task_count: int) -> None:
        self.active = active
        self.can_start = can_start
        self.reason = reason
        self.active_task_count = active_task_count


async def _blocked_reason(db: AsyncSession, company_id: uuid.UUID) -> str | None:
    """Return a specific block reason, or None when a cycle may start.

    Mirrors ``orchestrator._can_continue`` but disambiguates *why* it's blocked so
    the UI can show "Out of budget" vs "Spending paused" rather than a generic no.
    """
    company = await db.get(Company, company_id)
    if company is None or company.status is not CompanyStatus.active:
        return "not_active"

    spend_tripped = await db.scalar(
        select(CircuitBreaker.id).where(
            CircuitBreaker.company_id == company_id,
            CircuitBreaker.type == BreakerType.spend,
            CircuitBreaker.state == BreakerState.tripped,
        )
    )
    if spend_tripped is not None:
        return "spend_breaker"

    budget = await budget_svc.get_active_budget(db, company_id)
    if budget is None:
        return "insufficient_budget"
    remaining = budget.limit_cents - budget.spent_cents - budget.reserved_cents
    if remaining < settings.business_cycle_min_budget_cents:
        return "insufficient_budget"
    return None


async def start_cycle(db: AsyncSession, company: Company) -> CycleStart:
    """Start one business cycle for ``company`` if allowed; caller enqueues the task.

    Guards in order (matching the cron): company must be active; must not already
    have a live run (continuous mode may be looping); must pass the budget/breaker
    gate. On success creates the CEO scheduled run and returns its task id — the
    route commits and enqueues it.
    """
    if company.status is not CompanyStatus.active:
        return CycleStart(started=False, reason="not_active", active=False)

    # Don't stack a parallel run on a live cycle (cron does the same check).
    if await orchestrator.has_active_tasks(db, company.id):
        return CycleStart(started=False, reason="already_running", active=True)

    blocked = await _blocked_reason(db, company.id)
    if blocked is not None:
        return CycleStart(started=False, reason=blocked, active=False)

    task_id = await orchestrator.create_scheduled_run(db, company.id)
    if task_id is None:
        return CycleStart(started=False, reason="no_ceo", active=False)
    return CycleStart(started=True, reason="started", active=True, task_id=task_id)


async def cycle_status(db: AsyncSession, company: Company) -> CycleStatus:
    """Whether a cycle is running and whether a new one can be started right now."""
    count = await db.scalar(
        select(func.count(Task.id)).where(
            Task.company_id == company.id,
            Task.status.in_(orchestrator._ACTIVE_TASK_STATUSES),
        )
    )
    active = bool(count and count > 0)
    if active:
        return CycleStatus(active=True, can_start=False, reason="already_running", active_task_count=int(count or 0))
    blocked = await _blocked_reason(db, company.id)
    if blocked is not None:
        return CycleStatus(active=False, can_start=False, reason=blocked, active_task_count=0)
    return CycleStatus(active=False, can_start=True, reason="ready", active_task_count=0)
