"""Human worker binding — a person staffs a function slot (RFC 0001 step 6).

The third worker binding (§1a): a member of the company acts as the worker for a
function whose runtime is ``human``. They authenticate as a **user** (company
membership, not a per-function connection token — §9), then drive the *same*
Business-Function lifecycle an agent does: read the mandate, pull the next offered
initiative, claim it, and report the result. Every call reuses
``services.business_function``, so a human and an agent contribute to the company's
state through one identical contract — the machinery is the founder-in-the-loop
model promoted from "approver" to "does the initiative."

Only functions the founder has set to the ``human`` runtime are staffable here (an
agent-staffed function isn't a person's to claim), and the mandate is
segmented for the function's data-access policy before it's rendered to the person.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import CompanyDep, DbDep
from app.models import Agent
from app.models.enums import AgentBackendType
from app.services import business_function

router = APIRouter(prefix="/companies/{company_id}", tags=["human-worker"])


class ClaimBody(BaseModel):
    initiative_id: uuid.UUID


class ReportBody(BaseModel):
    initiative_id: uuid.UUID
    outcome: str  # done | failed | blocked | needs_decision
    summary: str = Field(default="", max_length=4000)


async def _human_function(db, *, company_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    """Resolve a function the founder has bound to a human worker, or 404/400."""
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "function not found")
    if agent.backend_type is not AgentBackendType.human:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "this function isn't staffed by a human — set its runtime to 'human' first",
        )
    return agent


@router.get("/functions/{agent_id}/work")
async def get_work(company: CompanyDep, agent_id: uuid.UUID, db: DbDep):
    """The human worker's view of a function: its mandate + the initiative on deck.

    Mirrors an agent pulling ``get_mandate`` + ``get_next_initiative``, rendered for
    a person. The mandate is data-segmented (it leaves the core to a human), so a
    function not cleared for financials won't surface money-denominated signals."""
    agent = await _human_function(db, company_id=company.id, agent_id=agent_id)
    mandate = await business_function.get_mandate(
        db, company_id=company.id, agent_id=agent.id, redact_for_access=True
    )
    initiative = await business_function.get_next_initiative(
        db, company_id=company.id, agent_id=agent.id
    )
    return {
        "function": agent.role.value,
        "function_title": agent.name,
        "mandate": mandate.model_dump(mode="json"),
        "initiative": initiative.model_dump(mode="json") if initiative else None,
    }


@router.post("/functions/{agent_id}/work/claim")
async def claim_work(company: CompanyDep, agent_id: uuid.UUID, body: ClaimBody, db: DbDep):
    """Claim the offered initiative so it's this person's to work (atomic)."""
    agent = await _human_function(db, company_id=company.id, agent_id=agent_id)
    claimed = await business_function.claim_initiative(
        db, company_id=company.id, agent_id=agent.id, task_id=body.initiative_id
    )
    await db.commit()
    return {
        "claimed": claimed is not None,
        "initiative": claimed.model_dump(mode="json") if claimed else None,
    }


@router.post("/functions/{agent_id}/work/report")
async def report_work(company: CompanyDep, agent_id: uuid.UUID, body: ReportBody, db: DbDep):
    """Report the outcome of an initiative — closes the loop exactly as an agent's
    ``report_result`` does (done/failed/blocked finalize; needs_decision escalates)."""
    await _human_function(db, company_id=company.id, agent_id=agent_id)  # 404/400 guard
    try:
        cost = await business_function.report_result(
            db,
            company_id=company.id,
            task_id=body.initiative_id,
            outcome=body.outcome,
            output={"summary": body.summary},
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return {"ok": True, "cost_cents": cost}
