"""Founder decision inbox: list pending, approve (resume task), reject (fail task)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent, DecisionRequest, MemoryEntry, Objective, Task
from app.models.enums import DecisionStatus, MemoryType, TaskStatus
from app.runtime.queue import enqueue_task
from app.schemas import DecisionOut, DecisionResolveRequest
from app.services import budget as budget_svc
from app.services import chat as chat_svc
from app.services import external_messages as ext

# Objective↔task keyword linkage lives with the objective-completion sweep so the
# inbox and the quest board agree on what "relates to this objective" means.
# Re-exported here under its historical name for existing callers and tests.
from app.services.objectives import keywords as _keywords

# Listing is company-scoped; resolve actions are by decision id (re-checked against membership).
router = APIRouter(tags=["decisions"])


def _best_objective(text_words: set[str], objectives: list[Objective]) -> str | None:
    """Best-effort link a decision's context to an objective by keyword overlap.

    Tasks carry no explicit objective foreign key, so we pick the objective whose
    title/rationale shares the most distinctive words with the triggering ask.
    Requires at least two overlapping words so a weak coincidence isn't surfaced
    as the "related objective".
    """
    best: tuple[int, str] | None = None
    for obj in objectives:
        overlap = len(text_words & _keywords(obj.title, obj.rationale))
        if overlap >= 2 and (best is None or overlap > best[0]):
            best = (overlap, obj.title)
    return best[1] if best else None


async def _to_out(db, decisions: list[DecisionRequest]) -> list[DecisionOut]:
    """Enrich each decision with the bigger picture: who raised it, the ask that
    triggered it, and the objective it relates to — so the founder sees context
    before diving into the specifics."""
    agent_ids = {d.agent_id for d in decisions if d.agent_id}
    agents: dict = {}
    if agent_ids:
        agents = {
            a.id: a
            for a in (await db.scalars(select(Agent).where(Agent.id.in_(agent_ids)))).all()
        }

    # Load the triggering tasks (the "ask") plus their parent task (the initiative).
    task_ids = {d.task_id for d in decisions if d.task_id}
    tasks: dict = {}
    if task_ids:
        tasks = {
            t.id: t
            for t in (await db.scalars(select(Task).where(Task.id.in_(task_ids)))).all()
        }
    parent_ids = {t.parent_task_id for t in tasks.values() if t.parent_task_id}
    parents: dict = {}
    if parent_ids:
        parents = {
            t.id: t
            for t in (await db.scalars(select(Task).where(Task.id.in_(parent_ids)))).all()
        }

    # Objectives per company, for best-effort objective linkage.
    company_ids = {d.company_id for d in decisions}
    objectives: dict = {}
    if company_ids:
        for o in (
            await db.scalars(select(Objective).where(Objective.company_id.in_(company_ids)))
        ).all():
            objectives.setdefault(o.company_id, []).append(o)

    out = []
    for d in decisions:
        item = DecisionOut.model_validate(d)
        agent = agents.get(d.agent_id)
        item.agent_name = agent.name if agent else None
        item.agent_role = agent.role.value if agent else None

        task = tasks.get(d.task_id) if d.task_id else None
        if task is not None:
            item.task_goal = task.goal
            parent = parents.get(task.parent_task_id) if task.parent_task_id else None
            # The initiative is the parent task's goal (the higher-level work the
            # CEO dispatched); a root task is its own initiative.
            item.initiative = parent.goal if parent is not None else task.goal
            item.objective_title = _best_objective(
                _keywords(task.goal, parent.goal if parent else None, d.summary),
                objectives.get(d.company_id, []),
            )
        out.append(item)
    return out


@router.get("/companies/{company_id}/decisions", response_model=list[DecisionOut])
async def list_decisions(company: CompanyDep, db: DbDep, only_pending: bool = True):
    stmt = (
        select(DecisionRequest)
        .where(DecisionRequest.company_id == company.id)
        .order_by(DecisionRequest.created_at.desc())
    )
    if only_pending:
        stmt = stmt.where(DecisionRequest.status == DecisionStatus.pending)
    return await _to_out(db, list((await db.scalars(stmt.limit(200))).all()))


async def _load_decision(db, user, decision_id: uuid.UUID) -> DecisionRequest:
    from app.models import Membership

    decision = await db.get(DecisionRequest, decision_id)
    if decision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    member = await db.scalar(
        select(Membership).where(
            Membership.company_id == decision.company_id, Membership.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Decision not found")
    return decision


async def _apply_note(db, decision: DecisionRequest, note: str | None) -> None:
    """Persist the founder's guidance and surface it to the agent on resume.

    The note is stored on the decision and written to company memory so the
    re-running agent recalls it — letting the founder *modify* how the action is
    carried out, not just approve/reject it.
    """
    note = (note or "").strip()
    if not note:
        return
    decision.payload = {**(decision.payload or {}), "founder_note": note}
    await db.execute(
        MemoryEntry.__table__.insert().values(
            company_id=decision.company_id,
            type=MemoryType.decision,
            title=f"Founder guidance on: {decision.summary[:80]}",
            content=note,
        )
    )


async def _post_resolution_dm(
    db, decision: DecisionRequest, *, resolution: str, note: str | None
) -> None:
    """Post the founder's verdict back into the decision's DM thread.

    Keeps the consolidated chat view honest: a structured decision surfaced as a
    founder DM gets a closing message when it's approved/rejected, so the thread
    reflects the outcome instead of going silent.
    """
    if decision.channel_id is None:
        return
    mark = "✅ Approved" if resolution == "approved" else "❌ Rejected"
    body = f"{mark}." + (f" {note.strip()}" if (note or "").strip() else "")
    await chat_svc.post_system_reply(
        db, company_id=decision.company_id, channel_id=decision.channel_id, body=body
    )


@router.post("/decisions/{decision_id}/approve", response_model=DecisionOut)
async def approve(
    decision_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    body: DecisionResolveRequest | None = Body(default=None),
):
    decision = await _load_decision(db, user, decision_id)
    decision.status = DecisionStatus.approved
    decision.resolved_by_user_id = user.id
    decision.resolved_at = datetime.now(UTC)
    await _apply_note(db, decision, body.note if body else None)
    await _post_resolution_dm(db, decision, resolution="approved", note=body.note if body else None)

    # Over-budget approvals carry the shortfall: authorising the spend lifts the
    # budget ceiling by that amount so the action goes through on resume. (The
    # actual top-up payment is wired in separately — this just clears the cap.)
    increase = int((decision.payload or {}).get("budget_increase_cents") or 0)
    if increase > 0:
        await budget_svc.increase_limit(
            db, company_id=decision.company_id, additional_cents=increase
        )

    resumed_task_id: uuid.UUID | None = None
    if decision.task_id:
        task = await db.get(Task, decision.task_id)
        # ``running`` is accepted alongside ``waiting_approval`` to recover tasks
        # that an earlier bug parked without flipping their status off ``running``.
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            task.status = TaskStatus.queued
            resumed_task_id = task.id
    await db.commit()
    if resumed_task_id is not None:
        await enqueue_task(resumed_task_id)
    return (await _to_out(db, [decision]))[0]


@router.post("/decisions/{decision_id}/reject", response_model=DecisionOut)
async def reject(
    decision_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    body: DecisionResolveRequest | None = Body(default=None),
):
    decision = await _load_decision(db, user, decision_id)
    decision.status = DecisionStatus.rejected
    decision.resolved_by_user_id = user.id
    decision.resolved_at = datetime.now(UTC)
    await _apply_note(db, decision, body.note if body else None)
    await _post_resolution_dm(db, decision, resolution="rejected", note=body.note if body else None)
    # If this gated an outbound message, mark its indexed record rejected so the
    # communications log shows it was never sent.
    await ext.mark_decision_resolved(db, decision_id=decision.id, approved=False)
    if decision.task_id:
        task = await db.get(Task, decision.task_id)
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            task.status = TaskStatus.failed
            task.output = {"rejected": True}
            task.transcript = None  # terminal: drop the working-memory checkpoint
    await db.commit()
    return (await _to_out(db, [decision]))[0]
