"""Founder decision inbox: list pending, approve (resume task), reject (fail task)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import DecisionRequest, Task
from app.models.enums import DecisionStatus, TaskStatus
from app.runtime.queue import enqueue_task
from app.schemas import DecisionOut

# Listing is company-scoped; resolve actions are by decision id (re-checked against membership).
router = APIRouter(tags=["decisions"])


@router.get("/companies/{company_id}/decisions", response_model=list[DecisionOut])
async def list_decisions(company: CompanyDep, db: DbDep, only_pending: bool = True):
    stmt = (
        select(DecisionRequest)
        .where(DecisionRequest.company_id == company.id)
        .order_by(DecisionRequest.created_at.desc())
    )
    if only_pending:
        stmt = stmt.where(DecisionRequest.status == DecisionStatus.pending)
    return (await db.scalars(stmt.limit(200))).all()


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


@router.post("/decisions/{decision_id}/approve", response_model=DecisionOut)
async def approve(decision_id: uuid.UUID, db: DbDep, user: CurrentUser):
    decision = await _load_decision(db, user, decision_id)
    decision.status = DecisionStatus.approved
    decision.resolved_by_user_id = user.id
    decision.resolved_at = datetime.now(UTC)

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
    return decision


@router.post("/decisions/{decision_id}/reject", response_model=DecisionOut)
async def reject(decision_id: uuid.UUID, db: DbDep, user: CurrentUser):
    decision = await _load_decision(db, user, decision_id)
    decision.status = DecisionStatus.rejected
    decision.resolved_by_user_id = user.id
    decision.resolved_at = datetime.now(UTC)
    if decision.task_id:
        task = await db.get(Task, decision.task_id)
        if task is not None and task.status in (
            TaskStatus.waiting_approval,
            TaskStatus.running,
        ):
            task.status = TaskStatus.failed
            task.output = {"rejected": True}
    await db.commit()
    return decision
