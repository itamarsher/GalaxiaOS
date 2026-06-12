"""Budget OS endpoints: spend view, runway, top-up."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, DbDep
from app.models import RunwaySnapshot
from app.schemas import BudgetOut, BudgetPatchRequest, BudgetView
from app.services import budget as budget_svc

router = APIRouter(prefix="/companies/{company_id}", tags=["budget"])


@router.get("/budget", response_model=BudgetView)
async def get_budget(company: CompanyDep, db: DbDep):
    budget = await budget_svc.get_active_budget(db, company.id)
    if budget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No budget")
    return BudgetView(
        budget=BudgetOut.model_validate(budget),
        by_category=await budget_svc.spend_by_category(db, company.id),
        by_agent=await budget_svc.spend_by_agent(db, company.id),
    )


@router.patch("/budget", response_model=BudgetOut)
async def patch_budget(company: CompanyDep, body: BudgetPatchRequest, db: DbDep):
    budget = await budget_svc.get_active_budget(db, company.id)
    if budget is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No budget")
    budget.limit_cents = body.limit_cents
    budget.version += 1
    await db.commit()
    return budget


@router.get("/runway")
async def get_runway(company: CompanyDep, db: DbDep):
    snap = await db.scalar(
        select(RunwaySnapshot)
        .where(RunwaySnapshot.company_id == company.id)
        .order_by(RunwaySnapshot.computed_at.desc())
        .limit(1)
    )
    if snap is None:
        return {"projected_days_remaining": None, "burn_rate_cents_per_day": 0, "balance_cents": None}
    return {
        "projected_days_remaining": snap.projected_days_remaining,
        "burn_rate_cents_per_day": snap.burn_rate_cents_per_day,
        "balance_cents": snap.balance_cents,
    }
