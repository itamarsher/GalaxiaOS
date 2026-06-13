"""Onboarding: start → (add key) → generate → preview → launch."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent, AgentEdge, Budget, Objective
from app.schemas import (
    AgentEdgeOut,
    AgentOut,
    CompanyOut,
    ObjectiveOut,
    OnboardingStartRequest,
    OrgChartOut,
    PreviewOut,
)
from app.services import onboarding
from app.runtime.queue import enqueue_task

router = APIRouter(tags=["onboarding"])


@router.post("/onboarding/start", response_model=CompanyOut)
async def start(body: OnboardingStartRequest, db: DbDep, user: CurrentUser):
    company = await onboarding.start(
        db,
        user=user,
        mission_text=body.mission_text,
        budget_cents=body.budget_cents,
        constraints=body.constraints,
    )
    await db.commit()
    return company


@router.post("/onboarding/{company_id}/generate", response_model=PreviewOut)
async def generate(company: CompanyDep, db: DbDep):
    try:
        result = await onboarding.generate(db, company=company)
    except onboarding.OnboardingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    preview = await _build_preview(db, company)
    preview.cost_estimate_cents = result.get("cost_estimate_cents")
    return preview


@router.get("/onboarding/{company_id}/preview", response_model=PreviewOut)
async def preview(company: CompanyDep, db: DbDep):
    return await _build_preview(db, company)


@router.post("/onboarding/{company_id}/launch", response_model=CompanyOut)
async def launch(company: CompanyDep, db: DbDep):
    task_id = await onboarding.launch(db, company=company)
    await db.commit()
    if task_id is not None:
        await enqueue_task(task_id)
    return company


async def _build_preview(db: DbDep, company) -> PreviewOut:
    objectives = (
        await db.scalars(
            select(Objective)
            .where(Objective.company_id == company.id)
            .order_by(Objective.priority)
        )
    ).all()
    agents = (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()
    edges = (await db.scalars(select(AgentEdge).where(AgentEdge.company_id == company.id))).all()
    return PreviewOut(
        company=CompanyOut.model_validate(company),
        objectives=[ObjectiveOut.model_validate(o) for o in objectives],
        org=OrgChartOut(
            agents=[AgentOut.model_validate(a) for a in agents],
            edges=[AgentEdgeOut.model_validate(e) for e in edges],
        ),
    )
