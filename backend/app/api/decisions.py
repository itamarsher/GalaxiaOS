"""Founder decision inbox: list pending, approve (resume task), reject (fail task)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent, DecisionRequest, MemoryEntry, Task
from app.models.enums import DecisionStatus, MemoryType, TaskStatus
from app.runtime.queue import enqueue_task
from app.schemas import DecisionChatRequest, DecisionOut, DecisionResolveRequest
from app.services import copilot

# Listing is company-scoped; resolve actions are by decision id (re-checked against membership).
router = APIRouter(tags=["decisions"])


async def _to_out(db, decisions: list[DecisionRequest]) -> list[DecisionOut]:
    """Attach the human-readable agent name to each decision."""
    agent_ids = {d.agent_id for d in decisions if d.agent_id}
    names: dict = {}
    if agent_ids:
        names = {
            a.id: a.name
            for a in (await db.scalars(select(Agent).where(Agent.id.in_(agent_ids)))).all()
        }
    out = []
    for d in decisions:
        item = DecisionOut.model_validate(d)
        item.agent_name = names.get(d.agent_id)
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


@router.post("/decisions/{decision_id}/chat")
async def chat(
    decision_id: uuid.UUID, body: DecisionChatRequest, db: DbDep, user: CurrentUser
):
    """Discuss a decision with the agent that raised it."""
    decision = await _load_decision(db, user, decision_id)
    answer = await copilot.discuss_decision(
        db, company_id=decision.company_id, decision=decision, message=body.message
    )
    await db.commit()
    return {"answer": answer}


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
    if decision.task_id:
        task = await db.get(Task, decision.task_id)
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            task.status = TaskStatus.failed
            task.output = {"rejected": True}
    await db.commit()
    return (await _to_out(db, [decision]))[0]
