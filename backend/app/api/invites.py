"""Team: the founder's roster + email invites (human binding, RFC 0001).

The founder sees the team (with each member's email, data access, and stated
involvement) and invites new teammates by email with pre-set access labels. An
invite is consumed when that email next authenticates (see
``services/invites.py`` + the auth paths). Everything here is **founder-only**.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Membership, User
from app.services import invites as invites_svc
from app.services import involvement as involvement_svc

router = APIRouter(prefix="/companies/{company_id}", tags=["team"])


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    name: str | None
    role: str
    involvement: str | None
    proposed_involvement: str | None
    coverage: str | None
    access_labels: list[str]


class InviteCreate(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    access_labels: list[str] = Field(default_factory=list)


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    access_labels: list[str]
    status: str


def _invite_out(inv) -> InviteOut:
    return InviteOut(
        id=inv.id, email=inv.email, role=inv.role.value,
        access_labels=inv.access_labels or [], status=inv.status.value,
    )


async def _require_founder(db, company, user) -> None:
    if not await involvement_svc.is_founder(db, company_id=company.id, user_id=user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the founder can do this")


@router.get("/members", response_model=list[MemberOut])
async def list_members(company: CompanyDep, db: DbDep, user: CurrentUser):
    """The company's humans, enriched with email + access + involvement (founder-only)."""
    await _require_founder(db, company, user)
    rows = await db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.company_id == company.id)
        .order_by(Membership.created_at.asc())
    )
    return [
        MemberOut(
            user_id=m.user_id, email=u.email, name=u.name, role=m.role.value,
            involvement=m.involvement, proposed_involvement=m.proposed_involvement,
            coverage=m.coverage, access_labels=m.access_labels or [],
        )
        for m, u in rows.all()
    ]


@router.get("/invites", response_model=list[InviteOut])
async def list_invites(company: CompanyDep, db: DbDep, user: CurrentUser):
    """Pending invites for the company (founder-only)."""
    await _require_founder(db, company, user)
    return [_invite_out(i) for i in await invites_svc.list_invites(db, company_id=company.id)]


@router.post("/invites", response_model=InviteOut, status_code=status.HTTP_201_CREATED)
async def create_invite(
    company: CompanyDep, body: InviteCreate, db: DbDep, user: CurrentUser
):
    """Invite a teammate by email with pre-set data access (founder-only)."""
    await _require_founder(db, company, user)
    try:
        inv = await invites_svc.create_invite(
            db, company_id=company.id, email=body.email, labels=body.access_labels,
            invited_by_user_id=user.id,
        )
    except invites_svc.InviteError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return _invite_out(inv)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    company: CompanyDep, invite_id: uuid.UUID, db: DbDep, user: CurrentUser
):
    """Withdraw a pending invite (founder-only)."""
    await _require_founder(db, company, user)
    try:
        await invites_svc.revoke_invite(db, company_id=company.id, invite_id=invite_id)
    except invites_svc.InviteError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return None
