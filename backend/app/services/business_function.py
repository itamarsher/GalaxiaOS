"""The Business-Function surface — the worker-agnostic contract of the control plane.

RFC 0001 (``docs/rfcs/0001-business-control-plane.md``) reframes Galaxia as a
*business control plane* that a hybrid workforce — internal agents, external
agents, humans — connects into. Whoever staffs a **function** (a slot in the
generated org) fetches its **mandate** (which function it is, the mission, its
objectives, budget envelope, current state), pulls its **next initiative**, does
the work, and **reports the result**.

This module is **migration step 1**: that surface, expressed as a first-class
service over the business services that already exist (``objectives``, ``budget``,
``metrics``, ``tasks``, and the mission/org models). It is deliberately a thin
orchestration layer — *no new business logic* — so that every worker binding drives
one contract instead of reaching into internals:

- the native loop consumes it directly (migration step 2);
- an MCP server exposes it to external agents (later);
- a UI/channel renders it for a human worker (later).

No transport and no behaviour change live here yet: this defines and implements the
operations and is covered by unit tests. Wiring the native loop to consume it is a
separate, follow-up change.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, Mission, Task
from app.models.enums import TaskStatus
from app.services import budget as budget_svc
from app.services import metrics as metrics_svc
from app.services import objectives as objectives_svc
from app.services import tasks as task_svc

# Active task states, in the order a worker cares about: an already-running
# initiative is the current one; otherwise the oldest queued piece is next.
_ACTIVE_STATES = (TaskStatus.running, TaskStatus.queued)

# The report outcomes a worker may return, mapped to the task's terminal status.
_OUTCOME_STATUS = {
    "done": TaskStatus.done,
    "failed": TaskStatus.failed,
    "blocked": TaskStatus.blocked,
}


class BudgetEnvelope(BaseModel):
    """What the function may still spend — its own slice and the company pool.

    ``*_remaining_cents`` is ``None`` when the corresponding limit is unset (an
    uncapped function inherits the company pool). All values are best-effort
    snapshots; the authoritative reservation still happens in ``CostMeter``.
    """

    function_limit_cents: int | None = None
    function_remaining_cents: int | None = None
    company_limit_cents: int | None = None
    company_remaining_cents: int | None = None


class Mandate(BaseModel):
    """Everything a worker needs to act as a function, assembled in one place.

    This is the structured form of the context the native loop assembles inline
    today (mission + objectives + metrics + budget); extracting it here is what
    lets a non-native worker receive the same briefing.
    """

    company_id: uuid.UUID
    function: str  # the agent's role, e.g. "growth"
    function_title: str  # the agent's display name, e.g. "Growth Lead"
    mission: str
    objectives: str  # numbered objectives + KRs block (stable handles)
    metrics: str  # recent real-world signals, summarised
    constraints: list[str]
    budget: BudgetEnvelope


class Initiative(BaseModel):
    """A unit of work offered to a function — today, a dispatched ``Task``."""

    id: uuid.UUID
    function: str
    goal: str
    status: str
    created_at: str
    budget: BudgetEnvelope


async def _budget_envelope(
    db: AsyncSession, *, company_id: uuid.UUID, agent: Agent
) -> BudgetEnvelope:
    """Snapshot the function's remaining slice and the company pool."""
    company_budget = await budget_svc.get_active_budget(db, company_id)
    company_limit = company_budget.limit_cents if company_budget else None
    company_remaining = (
        company_limit - company_budget.spent_cents - company_budget.reserved_cents
        if company_budget is not None
        else None
    )

    function_limit = agent.monthly_budget_cents
    function_remaining = (
        function_limit - await budget_svc.agent_spent(db, agent.id)
        if function_limit is not None
        else None
    )
    return BudgetEnvelope(
        function_limit_cents=function_limit,
        function_remaining_cents=function_remaining,
        company_limit_cents=company_limit,
        company_remaining_cents=company_remaining,
    )


async def get_mandate(
    db: AsyncSession, *, company_id: uuid.UUID, agent_id: uuid.UUID
) -> Mandate:
    """Assemble the function's mandate from the current business state.

    Reuses the same services the native loop reads (``objectives``, ``metrics``,
    ``budget``) plus the mission/org rows, so the briefing a worker receives is
    identical to what an in-process agent reasons from.
    """
    agent = await db.get(Agent, agent_id)
    if agent is None:
        raise ValueError(f"agent {agent_id} not found")

    mission = await db.scalar(select(Mission).where(Mission.company_id == company_id))
    mission_text = (mission.generated_summary or mission.raw_text) if mission else ""
    constraints = list(mission.constraints or []) if mission else []

    objectives = objectives_svc.objectives_prompt_block(
        await objectives_svc.ordered_objectives(db, company_id)
    )
    signals = await metrics_svc.latest_signals(
        db, company_id=company_id, limit=settings.metrics_recall_limit
    )
    return Mandate(
        company_id=company_id,
        function=agent.role.value,
        function_title=agent.name,
        mission=mission_text,
        objectives=objectives,
        metrics=metrics_svc.summarize_for_prompt(signals),
        constraints=constraints,
        budget=await _budget_envelope(db, company_id=company_id, agent=agent),
    )


async def get_next_initiative(
    db: AsyncSession, *, company_id: uuid.UUID, agent_id: uuid.UUID
) -> Initiative | None:
    """The next piece of work for this function, or ``None`` if idle.

    An already-``running`` task is the current initiative; otherwise the oldest
    ``queued`` one is next. Terminal and parked tasks are ignored.
    """
    task = await db.scalar(
        select(Task)
        .where(
            Task.company_id == company_id,
            Task.agent_id == agent_id,
            Task.status.in_(_ACTIVE_STATES),
        )
        # running before queued, then oldest-first, so the worker always sees the
        # single piece it should be doing now.
        .order_by(Task.status != TaskStatus.running, Task.created_at)
        .limit(1)
    )
    if task is None:
        return None
    agent = await db.get(Agent, agent_id)
    envelope = (
        await _budget_envelope(db, company_id=company_id, agent=agent)
        if agent is not None
        else BudgetEnvelope()
    )
    return Initiative(
        id=task.id,
        function=agent.role.value if agent is not None else "",
        goal=task.goal,
        status=task.status.value,
        created_at=task.created_at.isoformat(),
        budget=envelope,
    )


async def report_result(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    task_id: uuid.UUID,
    outcome: str,
    output: dict,
) -> int:
    """Close an initiative with a terminal outcome; returns its realised cost.

    A thin wrapper over ``tasks.finalize`` (which records the reputation outcome,
    propagates the result to company memory, drops the transcript, and stamps the
    cost) so every worker reports through one path. The caller commits.
    """
    status = _OUTCOME_STATUS.get(outcome)
    if status is None:
        raise ValueError(
            f"unknown outcome {outcome!r}; expected one of {sorted(_OUTCOME_STATUS)}"
        )
    task = await db.get(Task, task_id)
    if task is None or task.company_id != company_id:
        raise ValueError(f"task {task_id} not found for company {company_id}")
    return await task_svc.finalize(db, task=task, status=status, output=output)
