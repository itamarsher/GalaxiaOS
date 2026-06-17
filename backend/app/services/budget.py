"""Budget reservation/commit primitives and rollups.

The reservation is the atomic gate that makes "check budget BEFORE spending"
structurally true: it locks the budget row ``FOR UPDATE`` and refuses to reserve
beyond ``limit_cents``. Per-agent caps are enforced in the same transaction.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, Budget, SpendEntry
from app.models.enums import AgentStatus, SpendCategory


class BudgetExceeded(Exception):
    """Raised when a reservation would exceed the company or agent budget."""

    def __init__(self, scope: str, requested_cents: int, available_cents: int):
        self.scope = scope
        self.requested_cents = requested_cents
        self.available_cents = available_cents
        super().__init__(
            f"{scope} budget exceeded: requested {requested_cents}c, "
            f"available {available_cents}c"
        )


async def get_active_budget(db: AsyncSession, company_id: uuid.UUID) -> Budget | None:
    return await db.scalar(select(Budget).where(Budget.company_id == company_id).limit(1))


async def agent_spent(db: AsyncSession, agent_id: uuid.UUID) -> int:
    """An agent's committed + reserved spend so far (used to size its cap)."""
    total = await db.scalar(
        select(func.coalesce(func.sum(SpendEntry.amount_cents + SpendEntry.reserved_cents), 0)).where(
            SpendEntry.agent_id == agent_id
        )
    )
    return int(total or 0)


# Backwards-compatible private alias (kept for in-module call sites).
_agent_spent = agent_spent


async def allocation_overview(db: AsyncSession, company_id: uuid.UUID) -> dict | None:
    """The CEO's budget-allocation picture for org-management decisions.

    The company's monthly :class:`Budget` is the hard ceiling. Each agent's
    ``monthly_budget_cents`` is a soft cap reserving a slice of that ceiling for
    its own spend. The *pool* is the headroom not yet earmarked by anyone —
    what the CEO can hand to a newly hired (or resumed) agent::

        pool = (limit - spent - reserved) - Σ active agents' unspent allocation

    Only **active** agents earmark budget, so pausing an agent returns its
    unspent allocation to the pool (and resuming re-claims it). Returns ``None``
    when the company has no budget configured.
    """
    budget = await get_active_budget(db, company_id)
    if budget is None:
        return None
    ledger_free = budget.limit_cents - budget.spent_cents - budget.reserved_cents
    agents = (
        await db.scalars(
            select(Agent).where(
                Agent.company_id == company_id, Agent.status == AgentStatus.active
            )
        )
    ).all()
    earmarked = 0
    for agent in agents:
        if agent.monthly_budget_cents is None:
            continue
        used = await _agent_spent(db, agent.id)
        earmarked += max(0, agent.monthly_budget_cents - used)
    return {
        "limit_cents": int(budget.limit_cents),
        "spent_cents": int(budget.spent_cents),
        "reserved_cents": int(budget.reserved_cents),
        "earmarked_cents": int(earmarked),
        "pool_cents": int(ledger_free - earmarked),
    }


async def reserve(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    cents: int,
    agent_id: uuid.UUID | None = None,
) -> Budget:
    """Atomically reserve ``cents`` against the company (and agent) budget.

    Locks the budget row ``FOR UPDATE`` so concurrent reservations cannot race
    past ``limit_cents``. Raises :class:`BudgetExceeded` if over budget.
    """
    budget = await db.scalar(
        select(Budget).where(Budget.company_id == company_id).with_for_update().limit(1)
    )
    if budget is None:
        raise BudgetExceeded("company", cents, 0)

    available = budget.limit_cents - budget.spent_cents - budget.reserved_cents
    if cents > available:
        raise BudgetExceeded("company", cents, available)

    # Per-agent cap (optional), evaluated under the same lock.
    if agent_id is not None:
        agent = await db.get(Agent, agent_id)
        if agent is not None and agent.monthly_budget_cents is not None:
            agent_used = await _agent_spent(db, agent_id)
            agent_available = agent.monthly_budget_cents - agent_used
            if cents > agent_available:
                raise BudgetExceeded("agent", cents, agent_available)

    budget.reserved_cents += cents
    budget.version += 1
    await db.flush()
    return budget


async def increase_limit(
    db: AsyncSession, *, company_id: uuid.UUID, additional_cents: int
) -> Budget | None:
    """Raise the company's budget ceiling by ``additional_cents``.

    Used when the founder approves an over-budget request: the spend the agent
    asked for didn't fit, so the founder authorises more headroom (the actual
    top-up payment is wired in separately — this just lifts the cap so the
    approved action can proceed on resume). Locks the row ``FOR UPDATE`` and
    bumps ``version`` to stay consistent with the reserve/commit path.
    """
    if additional_cents <= 0:
        return None
    budget = await db.scalar(
        select(Budget).where(Budget.company_id == company_id).with_for_update().limit(1)
    )
    if budget is None:
        return None
    budget.limit_cents += additional_cents
    budget.version += 1
    await db.flush()
    return budget


async def commit_spend(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    budget_id: uuid.UUID,
    reserved_cents: int,
    actual_cents: int,
    category: SpendCategory,
    agent_id: uuid.UUID | None,
    task_id: uuid.UUID | None,
    vendor: str | None = None,
    sku: str | None = None,
    description: str | None = None,
) -> SpendEntry:
    """Release the reservation, record actual spend, and write the ledger row."""
    budget = await db.scalar(
        select(Budget).where(Budget.id == budget_id).with_for_update().limit(1)
    )
    if budget is None:  # pragma: no cover - defensive
        raise RuntimeError("budget vanished mid-transaction")

    budget.reserved_cents = max(0, budget.reserved_cents - reserved_cents)
    budget.spent_cents += actual_cents
    budget.version += 1

    entry = SpendEntry(
        company_id=company_id,
        budget_id=budget_id,
        agent_id=agent_id,
        task_id=task_id,
        category=category,
        amount_cents=actual_cents,
        reserved_cents=0,
        vendor=vendor,
        sku=sku,
        description=description,
    )
    db.add(entry)
    await db.flush()
    return entry


async def release_reservation(
    db: AsyncSession, *, budget_id: uuid.UUID, reserved_cents: int
) -> None:
    """Release a reservation without recording spend (e.g. on action failure)."""
    budget = await db.scalar(
        select(Budget).where(Budget.id == budget_id).with_for_update().limit(1)
    )
    if budget is not None:
        budget.reserved_cents = max(0, budget.reserved_cents - reserved_cents)
        budget.version += 1
        await db.flush()


async def spend_by_category(db: AsyncSession, company_id: uuid.UUID) -> dict[str, int]:
    rows = await db.execute(
        select(SpendEntry.category, func.coalesce(func.sum(SpendEntry.amount_cents), 0))
        .where(SpendEntry.company_id == company_id)
        .group_by(SpendEntry.category)
    )
    return {cat.value: int(total) for cat, total in rows.all()}


async def spend_by_agent(db: AsyncSession, company_id: uuid.UUID) -> dict[str, int]:
    rows = await db.execute(
        select(SpendEntry.agent_id, func.coalesce(func.sum(SpendEntry.amount_cents), 0))
        .where(SpendEntry.company_id == company_id, SpendEntry.agent_id.is_not(None))
        .group_by(SpendEntry.agent_id)
    )
    return {str(agent_id): int(total) for agent_id, total in rows.all()}


async def spend_detail_by_agent(db: AsyncSession, company_id: uuid.UUID) -> list[dict]:
    """Per-agent spend with the underlying ledger entries (for the expandable view).

    Grouped by agent and sorted by total spend desc; each agent carries its
    individual :class:`SpendEntry` rows so the UI can expand to the full detail.
    """
    agents = {
        a.id: a
        for a in (await db.scalars(select(Agent).where(Agent.company_id == company_id))).all()
    }
    entries = (
        await db.scalars(
            select(SpendEntry)
            .where(SpendEntry.company_id == company_id)
            .order_by(SpendEntry.created_at.desc())
        )
    ).all()

    grouped: dict[uuid.UUID | None, list[SpendEntry]] = {}
    for entry in entries:
        grouped.setdefault(entry.agent_id, []).append(entry)

    out: list[dict] = []
    for agent_id, rows in grouped.items():
        agent = agents.get(agent_id) if agent_id is not None else None
        out.append(
            {
                "agent_id": agent_id,
                "agent_name": agent.name if agent else None,
                "agent_role": agent.role.value if agent else None,
                "total_cents": sum(int(r.amount_cents) for r in rows),
                "entries": rows,
            }
        )
    out.sort(key=lambda g: g["total_cents"], reverse=True)
    return out
