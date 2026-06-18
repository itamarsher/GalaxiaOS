"""Task lifecycle helpers shared by the agent loop and the CEO audit tools.

A delegated agent's result does not go straight to ``done``: it first lands in
``auditing``, where the CEO reviews it and either accepts it (forward → ``done``)
or challenges it (backward → re-queued with the CEO's comments). Keeping the
finalisation and audit transitions here means a task wound down via the normal
loop or via the CEO's audit behaves identically.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, SpendEntry, Task
from app.models.enums import AgentRole, AgentStatus, MemoryType, TaskStatus
from app.runtime import breakers
from app.services import memory, reputation


async def finalize(
    db: AsyncSession, *, task: Task, status: TaskStatus, output: dict
) -> int:
    """Apply a terminal ``status`` to a task and wind it down.

    Records the reputation outcome, propagates a delegated result to company
    memory (so it resurfaces to the parent/CEO via recall), drops the working
    transcript, and stamps the realised cost. Returns the task's cost in cents.
    Shared by the native loop's normal finish and the CEO's audit-approve.
    """
    row = await db.get(Task, task.id)
    if row is None:  # pragma: no cover
        return 0
    row.status = status
    row.output = output
    row.transcript = None  # terminal: drop the working-memory checkpoint
    cost = await db.scalar(
        select(func.coalesce(func.sum(SpendEntry.amount_cents), 0)).where(
            SpendEntry.task_id == row.id
        )
    )
    row.cost_cents = int(cost or 0)
    await reputation.record_task_outcome(
        db,
        company_id=row.company_id,
        agent_id=row.agent_id,
        success=status is TaskStatus.done,
        blocked=status is TaskStatus.blocked,
        cost_cents=row.cost_cents,
    )
    if status is TaskStatus.done and row.parent_task_id is not None:
        try:
            # Savepoint: a failed propagation rolls back only this write, leaving
            # the outer transaction (the actual finish) intact.
            async with db.begin_nested():
                await memory.write(
                    db,
                    company_id=row.company_id,
                    type=MemoryType.result,
                    title=f"Result: {row.goal[:80]}",
                    content=output.get("summary", "") or "(no summary)",
                    source_task_id=row.id,
                )
        except Exception:  # noqa: BLE001 — propagation must not fail finish
            pass
    return row.cost_cents


async def should_audit(db: AsyncSession, *, agent: Agent, task: Task) -> bool:
    """Whether this finished result must be audited by the CEO before it's done.

    True only for a result the CEO delegated: the finishing agent isn't the CEO,
    the task was dispatched by the CEO (its parent task belongs to the CEO), and
    the per-task reopen cap hasn't been reached (so an audit↔redo loop ends).
    """
    if agent.role is AgentRole.ceo or task.parent_task_id is None:
        return False
    if int((task.input or {}).get("audit_rounds", 0)) >= settings.max_audit_rounds:
        return False
    parent = await db.get(Task, task.parent_task_id)
    if parent is None or parent.agent_id is None:
        return False
    parent_agent = await db.get(Agent, parent.agent_id)
    return parent_agent is not None and parent_agent.role is AgentRole.ceo


async def begin_auditing(
    db: AsyncSession, *, child_id: uuid.UUID, output: dict
) -> uuid.UUID | None:
    """Park ``child_id``'s result in ``auditing`` and create a CEO task to review it.

    Keeps the child's transcript so a reopen resumes with full prior context.
    Returns the new CEO audit task id to enqueue, or ``None`` if there's no active
    CEO to audit (the caller then finishes the child as ``done`` normally).
    """
    child = await db.get(Task, child_id)
    if child is None:  # pragma: no cover
        return None
    ceo = await db.scalar(
        select(Agent).where(
            Agent.company_id == child.company_id,
            Agent.role == AgentRole.ceo,
            Agent.status == AgentStatus.active,
        )
    )
    if ceo is None:
        return None

    child.status = TaskStatus.auditing
    child.output = output  # transcript is deliberately left intact for a reopen
    await db.flush()

    child_agent = await db.get(Agent, child.agent_id) if child.agent_id else None
    role_name = child_agent.role.value if child_agent else "agent"
    rounds = int((child.input or {}).get("audit_rounds", 0))
    goal = (
        f"AUDIT the result of a {role_name} task before it is accepted.\n\n"
        f"Task: {child.goal}\n\n"
        f"Reported result:\n{output.get('summary') or '(no summary)'}\n\n"
        "Review it critically against the mission and what the company knows. If it "
        f"genuinely meets the bar, accept it: `audit_task` with task_id {child.id}, "
        "decision 'approve'. If it falls short, challenge it: `audit_task` with "
        "decision 'reopen' and specific comments on what to fix — your comments are "
        "handed to the agent as its first instruction when it resumes with its full "
        "prior context. Then finish with `report_result`."
    )
    audit = Task(
        company_id=child.company_id,
        run_id=child.run_id,
        root_run_id=child.root_run_id,
        agent_id=ceo.id,
        parent_task_id=child.id,
        depth=child.depth + 1,
        goal=goal,
        input={"audit_target_task_id": str(child.id)},
        status=TaskStatus.queued,
        loop_signature=breakers.loop_signature(ceo.id, f"audit {child.id} r{rounds}"),
    )
    db.add(audit)
    await db.flush()
    return audit.id
