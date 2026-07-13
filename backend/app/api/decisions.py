"""Founder decision inbox: list pending, approve (resume task), reject (resume + adapt).

Resolution here is the game's explicit approve/reject click; the chat surface now
resolves the same decisions by classifying a plain founder reply. Both paths share
:mod:`app.services.decisions`, so they behave identically.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent, DecisionRequest, Objective, Task
from app.models.enums import DecisionStatus
from app.runtime.queue import enqueue_task
from app.schemas import DecisionOut, DecisionResolveRequest
from app.services import decisions as decisions_svc

# Listing is company-scoped; resolve actions are by decision id (re-checked against membership).
router = APIRouter(tags=["decisions"])


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

    # Objective linkage is explicit: a task carries the objective_id the CEO tagged
    # it with, so we just look the title up by id (no keyword guessing).
    objective_ids = {t.objective_id for t in tasks.values() if t.objective_id}
    objective_titles: dict = {}
    if objective_ids:
        objective_titles = {
            o.id: o.title
            for o in (
                await db.scalars(select(Objective).where(Objective.id.in_(objective_ids)))
            ).all()
        }

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
            item.objective_title = objective_titles.get(task.objective_id)
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


@router.post("/decisions/{decision_id}/approve", response_model=DecisionOut)
async def approve(
    decision_id: uuid.UUID,
    db: DbDep,
    user: CurrentUser,
    body: DecisionResolveRequest | None = Body(default=None),
):
    decision = await _load_decision(db, user, decision_id)
    resumed_task_id = await decisions_svc.resolve_decision(
        db, decision, approved=True, user_id=user.id, note=body.note if body else None
    )
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
    resumed_task_id = await decisions_svc.resolve_decision(
        db, decision, approved=False, user_id=user.id, note=body.note if body else None
    )
    await db.commit()
    if resumed_task_id is not None:
        await enqueue_task(resumed_task_id)
    return (await _to_out(db, [decision]))[0]
