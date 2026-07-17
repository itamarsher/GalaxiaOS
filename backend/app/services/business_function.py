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
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, Mission, Task
from app.models.enums import TaskStatus
from app.services import budget as budget_svc
from app.services import chat as chat_svc
from app.services import metrics as metrics_svc
from app.services import objectives as objectives_svc
from app.services import tasks as task_svc

# Active task states, in the order a worker cares about: an already-running
# initiative is the current one; otherwise the oldest queued piece is next.
_ACTIVE_STATES = (TaskStatus.running, TaskStatus.queued)

# Terminal report outcomes, mapped to the task's final status (via tasks.finalize).
_TERMINAL_STATUS = {
    "done": TaskStatus.done,
    "failed": TaskStatus.failed,
    "blocked": TaskStatus.blocked,
}
# A worker may also report that it cannot proceed without a founder decision. This
# is NOT terminal — the initiative parks and escalates rather than finalizing.
_NEEDS_DECISION = "needs_decision"
_OUTCOMES = frozenset(_TERMINAL_STATUS) | {_NEEDS_DECISION}


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
    language: str | None  # founder's language, detected at onboarding; pins outputs
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
        language=mission.language if mission else None,
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


async def claim_initiative(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    agent_id: uuid.UUID,
    task_id: uuid.UUID,
    lease_seconds: int | None = None,
) -> Initiative | None:
    """Atomically claim an offered initiative for this worker (async-first lifecycle).

    A single conditional UPDATE that only matches a still-``queued`` task belonging
    to this function, so two pull workers can never both take the same initiative —
    the loser gets ``None`` and asks for the next one. Sets a lease so a dead or slow
    worker's claim can later be reclaimed (see :func:`release_expired_claims`).
    Returns the claimed Initiative, or ``None`` if it was already taken or isn't this
    function's to claim. The caller commits.
    """
    lease = settings.initiative_lease_seconds if lease_seconds is None else lease_seconds
    expires = datetime.now(timezone.utc) + timedelta(seconds=lease)
    result = await db.execute(
        update(Task)
        .where(
            Task.id == task_id,
            Task.company_id == company_id,
            Task.agent_id == agent_id,
            Task.status == TaskStatus.queued,
        )
        .values(status=TaskStatus.running, lease_expires_at=expires)
    )
    if result.rowcount != 1:
        return None
    task = await db.get(Task, task_id)
    if task is None:  # pragma: no cover - just-updated row must exist
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
        status=TaskStatus.running.value,  # authoritative: the claim just set it
        created_at=task.created_at.isoformat(),
        budget=envelope,
    )


async def release_expired_claims(
    db: AsyncSession, *, company_id: uuid.UUID, now: datetime | None = None
) -> int:
    """Return lease-expired initiatives to the offered pool for reassignment.

    Only *leased* running tasks (claimed via :func:`claim_initiative`) whose lease
    has passed are reset to ``queued`` and un-leased; push-run tasks (lease NULL) are
    never touched, so the native loop is unaffected. Returns how many were
    reassigned. The caller commits.
    """
    cutoff = now or datetime.now(timezone.utc)
    result = await db.execute(
        update(Task)
        .where(
            Task.company_id == company_id,
            Task.status == TaskStatus.running,
            Task.lease_expires_at.is_not(None),
            Task.lease_expires_at < cutoff,
        )
        .values(status=TaskStatus.queued, lease_expires_at=None)
    )
    return result.rowcount or 0


async def report_result(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    task_id: uuid.UUID,
    outcome: str,
    output: dict,
) -> int:
    """Report the outcome of an initiative; returns its realised cost (0 if parked).

    ``done`` / ``failed`` / ``blocked`` are **terminal**: a thin wrapper over
    ``tasks.finalize`` (which records the reputation outcome, propagates the result
    to company memory, drops the transcript, and stamps the cost), so every worker
    finishes through one path.

    ``needs_decision`` is **not** terminal: the worker cannot proceed without a
    founder decision. The initiative parks (``waiting_approval``) and the ask is
    escalated to the founder's DM (the unified decision inbox) — the transcript is
    kept so the worker can resume once the founder replies. ``output`` must carry a
    ``summary`` describing what the founder must decide. The caller commits.
    """
    if outcome not in _OUTCOMES:
        raise ValueError(f"unknown outcome {outcome!r}; expected one of {sorted(_OUTCOMES)}")
    task = await db.get(Task, task_id)
    if task is None or task.company_id != company_id:
        raise ValueError(f"task {task_id} not found for company {company_id}")

    # Reporting ends the claim: drop any lease so a reported/parked initiative is
    # never reclaimed by release_expired_claims.
    task.lease_expires_at = None

    if outcome == _NEEDS_DECISION:
        return await _park_for_decision(db, task=task, output=output)
    return await task_svc.finalize(db, task=task, status=_TERMINAL_STATUS[outcome], output=output)


async def _park_for_decision(db: AsyncSession, *, task: Task, output: dict) -> int:
    """Park an initiative on a founder decision and escalate it to their DM.

    Deliberately does NOT finalize: the task stays ``waiting_approval`` with its
    transcript intact so it can resume when the founder replies. The escalation is a
    message in the agent↔founder thread (the codebase's unified decision inbox),
    posted through the chat service so it works for any worker binding.
    """
    summary = str(output.get("summary") or "").strip()
    if not summary:
        raise ValueError(
            "a needs_decision result must include a 'summary' describing what the "
            "founder must decide"
        )
    channel = await chat_svc.founder_dm(
        db, company_id=task.company_id, agent_id=task.agent_id
    )
    await chat_svc.post_message(
        db,
        company_id=task.company_id,
        channel_id=channel.id,
        sender_agent_id=task.agent_id,
        body=summary,
    )
    task.status = TaskStatus.waiting_approval
    task.output = output
    await db.flush()
    return task.cost_cents or 0
