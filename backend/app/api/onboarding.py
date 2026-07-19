"""Onboarding: start → (add key) → generate → preview → launch."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent, AgentEdge, InvestmentReview, Objective
from app.runtime.queue import enqueue_task
from app.schemas import (
    AgentEdgeOut,
    AgentOut,
    CompanyOut,
    GenerationProgressOut,
    InvestmentReviewOut,
    ObjectiveOut,
    OnboardingStartRequest,
    OrgChartOut,
    PreviewOut,
    RefineRequest,
    RefineResponse,
    ReusableCredentialOut,
    ReuseCredentialsRequest,
    ReuseCredentialsResponse,
)
from app.services import investors, onboarding, onboarding_reuse

router = APIRouter(tags=["onboarding"])


@router.post("/onboarding/start", response_model=CompanyOut)
async def start(body: OnboardingStartRequest, db: DbDep, user: CurrentUser):
    company = await onboarding.start(
        db,
        user=user,
        mission_text=body.mission_text,
        budget_cents=body.budget_cents,
        constraints=body.constraints,
        involvement=body.involvement,
    )
    await db.commit()
    return company


@router.get(
    "/onboarding/{company_id}/reusable-credentials",
    response_model=list[ReusableCredentialOut],
)
async def reusable_credentials(company: CompanyDep, user: CurrentUser):
    """Keys/connections from the founder's other companies, reusable into this one.

    Lets a new business pick up the Anthropic key, Cloudflare, Google Drive or MCP
    servers already configured elsewhere instead of re-entering them. Never returns
    a secret — only display fingerprints/labels.
    """
    return await onboarding_reuse.list_reusable(
        user_id=user.id, target_company_id=company.id
    )


@router.post(
    "/onboarding/{company_id}/reuse-credentials",
    response_model=ReuseCredentialsResponse,
)
async def reuse_credentials(
    company: CompanyDep, body: ReuseCredentialsRequest, db: DbDep, user: CurrentUser
):
    """Copy the selected saved credentials into this company (envelope re-sealed)."""
    reused = await onboarding_reuse.reuse(
        db, user_id=user.id, target_company_id=company.id, ids=body.ids
    )
    await db.commit()
    return ReuseCredentialsResponse(reused=reused)


@router.post("/onboarding/{company_id}/generate", response_model=PreviewOut)
async def generate(company: CompanyDep, db: DbDep):
    onboarding.reset_progress(company.id)
    try:
        result = await onboarding.generate(db, company=company)
    except onboarding.OnboardingError as exc:
        onboarding.set_progress(
            company.id, phase="error", pct=100, message=str(exc), status="error", error=str(exc)
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surface a terminal state to the poller, then re-raise
        onboarding.set_progress(
            company.id,
            phase="error",
            pct=100,
            message="Generation failed",
            status="error",
            error=str(exc),
        )
        raise
    await db.commit()
    preview = await _build_preview(db, company)
    preview.cost_estimate_cents = result.get("cost_estimate_cents")
    onboarding.set_progress(
        company.id, phase="done", pct=100, message="Organization ready", status="done"
    )
    return preview


@router.get("/onboarding/{company_id}/generate/status", response_model=GenerationProgressOut)
async def generate_status(company: CompanyDep):
    progress = onboarding.get_progress(company.id)
    if progress is None:
        return GenerationProgressOut(
            phase="idle", pct=0, message="Not started", status="idle"
        )
    return GenerationProgressOut(**progress)


@router.post("/onboarding/{company_id}/refine", response_model=RefineResponse)
async def refine(company: CompanyDep, body: RefineRequest, db: DbDep):
    try:
        result = await onboarding.refine(db, company=company, message=body.message)
    except onboarding.OnboardingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    preview = await _build_preview(db, company)
    preview.cost_estimate_cents = result.get("cost_estimate_cents")
    return RefineResponse(reply=result["reply"], preview=preview)


@router.post(
    "/onboarding/{company_id}/investment-review",
    response_model=list[InvestmentReviewOut],
)
async def investment_review(company: CompanyDep, db: DbDep):
    try:
        reviews = await investors.review(db, company=company)
    except (investors.InvestorError, onboarding.OnboardingError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return [InvestmentReviewOut.model_validate(r) for r in reviews]


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
    reviews = (
        await db.scalars(
            select(InvestmentReview).where(InvestmentReview.company_id == company.id)
        )
    ).all()
    return PreviewOut(
        company=CompanyOut.model_validate(company),
        objectives=[ObjectiveOut.model_validate(o) for o in objectives],
        org=OrgChartOut(
            agents=[AgentOut.model_validate(a) for a in agents],
            edges=[AgentEdgeOut.model_validate(e) for e in edges],
        ),
        investment_reviews=[InvestmentReviewOut.model_validate(r) for r in reviews],
    )
