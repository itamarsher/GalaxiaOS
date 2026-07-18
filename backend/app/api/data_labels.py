"""Data-segmentation management — founder-controlled taxonomy + access policy.

The founder owns the company's data classification: they manage the label taxonomy
(seeded with defaults, then editable), and they set which labels each agent/human
may be given — the multiple-choice-of-available-labels policy provided at hire /
onboarding time. All endpoints are founder-only.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Membership
from app.models.enums import MembershipRole
from app.services import data_policy

router = APIRouter(prefix="/companies/{company_id}", tags=["data-labels"])


class LabelCreate(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class LabelUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class AccessLabelsSet(BaseModel):
    labels: list[str] = Field(default_factory=list)


class LabelOut(BaseModel):
    key: str
    name: str
    description: str | None
    is_default: bool


def _out(label) -> LabelOut:
    return LabelOut(key=label.key, name=label.name, description=label.description,
                    is_default=label.is_default)


async def _require_founder(db, company, user) -> None:
    m = await db.scalar(
        select(Membership).where(
            Membership.company_id == company.id, Membership.user_id == user.id
        )
    )
    if m is None or m.role is not MembershipRole.founder:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the founder can do this")


@router.get("/data-labels", response_model=list[LabelOut])
async def list_data_labels(company: CompanyDep, db: DbDep, user: CurrentUser):
    """The company's label taxonomy (seeded with defaults on first access)."""
    await _require_founder(db, company, user)
    labels = await data_policy.list_labels(db, company.id)
    await db.commit()  # persist a first-time seed
    return [_out(x) for x in labels]


@router.post("/data-labels", response_model=LabelOut, status_code=status.HTTP_201_CREATED)
async def create_data_label(company: CompanyDep, body: LabelCreate, db: DbDep, user: CurrentUser):
    await _require_founder(db, company, user)
    try:
        label = await data_policy.create_label(
            db, company.id, key=body.key, name=body.name, description=body.description
        )
    except data_policy.DataPolicyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    return _out(label)


@router.put("/data-labels/{key}", response_model=LabelOut)
async def update_data_label(
    company: CompanyDep, key: str, body: LabelUpdate, db: DbDep, user: CurrentUser
):
    await _require_founder(db, company, user)
    try:
        label = await data_policy.update_label(
            db, company.id, key, name=body.name, description=body.description
        )
    except data_policy.DataPolicyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()
    return _out(label)


@router.delete("/data-labels/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_label(company: CompanyDep, key: str, db: DbDep, user: CurrentUser):
    await _require_founder(db, company, user)
    try:
        await data_policy.delete_label(db, company.id, key)
    except data_policy.DataPolicyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    await db.commit()


@router.put("/agents/{agent_id}/access-labels", response_model=AccessLabelsSet)
async def set_agent_access_labels(
    company: CompanyDep, agent_id: uuid.UUID, body: AccessLabelsSet, db: DbDep, user: CurrentUser
):
    """Founder sets which labels a hired agent may be given (multiple-choice)."""
    await _require_founder(db, company, user)
    try:
        agent = await data_policy.set_agent_access(db, company.id, agent_id, body.labels)
    except data_policy.DataPolicyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return AccessLabelsSet(labels=agent.access_labels or [])


@router.put("/members/{user_id}/access-labels", response_model=AccessLabelsSet)
async def set_member_access_labels(
    company: CompanyDep, user_id: uuid.UUID, body: AccessLabelsSet, db: DbDep, user: CurrentUser
):
    """Founder sets which labels a human teammate may be given (multiple-choice)."""
    await _require_founder(db, company, user)
    try:
        m = await data_policy.set_member_access(db, company.id, user_id, body.labels)
    except data_policy.DataPolicyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await db.commit()
    return AccessLabelsSet(labels=m.access_labels or [])
