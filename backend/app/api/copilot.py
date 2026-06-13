"""Founder Copilot endpoints: latest digest + NL ask."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.deps import CompanyDep, DbDep
from app.models import FounderDigest
from app.schemas import CopilotAskRequest, CopilotAskResponse
from app.services import copilot

router = APIRouter(prefix="/companies/{company_id}", tags=["copilot"])


@router.get("/digest/latest")
async def latest_digest(company: CompanyDep, db: DbDep):
    digest = await db.scalar(
        select(FounderDigest)
        .where(FounderDigest.company_id == company.id)
        .order_by(FounderDigest.period_date.desc())
        .limit(1)
    )
    if digest is None:
        return {"summary_md": None, "open_decisions": 0, "period_date": None}
    return {
        "summary_md": digest.summary_md,
        "open_decisions": digest.open_decisions,
        "period_date": digest.period_date.isoformat(),
    }


@router.post("/copilot/ask", response_model=CopilotAskResponse)
async def ask(company: CompanyDep, body: CopilotAskRequest, db: DbDep):
    text, kind = await copilot.answer(db, company_id=company.id, question=body.question)
    await db.commit()
    return CopilotAskResponse(answer=text, kind=kind)


@router.post("/digest/generate")
async def generate_digest(company: CompanyDep, db: DbDep):
    digest = await copilot.generate_digest(db, company_id=company.id)
    await db.commit()
    return {
        "summary_md": digest.summary_md,
        "open_decisions": digest.open_decisions,
        "period_date": digest.period_date.isoformat(),
    }
