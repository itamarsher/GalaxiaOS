"""Human involvement preferences — the founder-controlled human-binding policy.

The founder is always in ultimate control: setting a member's active involvement
and approving a proposal are **founder-only**; a member may only *propose* their
own involvement, which is inert until the founder approves it. See
``services/involvement.py`` for the invariants.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.deps import CompanyDep, CurrentUser, DbDep
from app.services import involvement as involvement_svc

router = APIRouter(prefix="/companies/{company_id}", tags=["involvement"])


class InvolvementSet(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    coverage: str | None = Field(default=None, max_length=500)


class InvolvementPropose(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class InvolvementApprove(BaseModel):
    # Optional founder edit applied before approving; omit to approve as proposed.
    text: str | None = Field(default=None, max_length=4000)


class InvolvementOut(BaseModel):
    user_id: uuid.UUID
    role: str
    involvement: str | None
    proposed_involvement: str | None
    coverage: str | None


def _out(m) -> InvolvementOut:
    return InvolvementOut(
        user_id=m.user_id, role=m.role.value, involvement=m.involvement,
        proposed_involvement=m.proposed_involvement, coverage=m.coverage,
    )


async def _require_founder(db, company, user) -> None:
    if not await involvement_svc.is_founder(db, company_id=company.id, user_id=user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the founder can do this")


@router.get("/involvement", response_model=list[InvolvementOut])
async def list_involvement(company: CompanyDep, db: DbDep, user: CurrentUser):
    """The team's involvement (founder-only) — the router's input."""
    await _require_founder(db, company, user)
    members = await involvement_svc.team_involvement(db, company_id=company.id)
    return [_out(m) for m in members]


@router.put("/members/{user_id}/involvement", response_model=InvolvementOut)
async def set_member_involvement(
    company: CompanyDep, user_id: uuid.UUID, body: InvolvementSet, db: DbDep, user: CurrentUser
):
    """Founder sets a member's ACTIVE involvement directly (provide)."""
    await _require_founder(db, company, user)
    try:
        m = await involvement_svc.set_involvement(
            db, company_id=company.id, user_id=user_id, text=body.text, coverage=body.coverage
        )
    except involvement_svc.InvolvementError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return _out(m)


@router.put("/involvement/proposal", response_model=InvolvementOut)
async def propose_own_involvement(
    company: CompanyDep, body: InvolvementPropose, db: DbDep, user: CurrentUser
):
    """A member proposes their OWN involvement — inert until the founder approves."""
    try:
        m = await involvement_svc.propose_involvement(
            db, company_id=company.id, user_id=user.id, text=body.text
        )
    except involvement_svc.InvolvementError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return _out(m)


@router.post("/members/{user_id}/involvement/approve", response_model=InvolvementOut)
async def approve_member_involvement(
    company: CompanyDep, user_id: uuid.UUID, body: InvolvementApprove, db: DbDep, user: CurrentUser
):
    """Founder approves a member's pending proposal (optionally editing it first)."""
    await _require_founder(db, company, user)
    try:
        m = await involvement_svc.approve_involvement(
            db, company_id=company.id, user_id=user_id, edited_text=body.text
        )
    except involvement_svc.InvolvementError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _out(m)
