"""Company secret endpoints — store, list (fingerprint only), revoke, and fulfil an
agent's request.

Every response exposes fingerprints only; a plaintext value is accepted on the way
in (create / fulfil) and sealed immediately, and is never returned. Fulfilling an
agent's ``secret_request`` decision goes through :func:`secrets.fulfill_request`,
which — unlike the ordinary decision-reply path — never writes the value to a memory
note, DM, or the decision payload.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import DecisionRequest, Membership
from app.models.enums import DecisionKind, DecisionStatus
from app.runtime.queue import enqueue_task
from app.schemas import SecretCreateRequest, SecretFulfillRequest, SecretOut
from app.services import secrets as secrets_svc

router = APIRouter(prefix="/companies/{company_id}/secrets", tags=["secrets"])
# Fulfilment is keyed by decision id (re-checked against membership), like the
# approve/reject endpoints in app.api.decisions.
decisions_router = APIRouter(tags=["secrets"])


@router.post("", response_model=SecretOut)
async def add_secret(company: CompanyDep, body: SecretCreateRequest, db: DbDep):
    try:
        secret = await secrets_svc.store_secret(
            db,
            company_id=company.id,
            name=body.name,
            plaintext=body.value,
            description=body.description,
            allowed_host=body.allowed_host,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    return secret


@router.get("", response_model=list[SecretOut])
async def list_secrets(company: CompanyDep, db: DbDep):
    return await secrets_svc.list_secrets(db, company_id=company.id)


@router.delete("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(company: CompanyDep, secret_id: uuid.UUID, db: DbDep):
    removed = await secrets_svc.revoke_secret(db, company_id=company.id, secret_id=secret_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Secret not found")
    await db.commit()


@decisions_router.post("/decisions/{decision_id}/fulfill-secret", response_model=SecretOut)
async def fulfill_secret(
    decision_id: uuid.UUID, body: SecretFulfillRequest, db: DbDep, user: CurrentUser
):
    decision = await db.get(DecisionRequest, decision_id)
    if decision is None or decision.kind != DecisionKind.secret_request:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Secret request not found")
    member = await db.scalar(
        select(Membership).where(
            Membership.company_id == decision.company_id, Membership.user_id == user.id
        )
    )
    if member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Secret request not found")
    if decision.status != DecisionStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "This request is already resolved")

    try:
        resumed_task_id = await secrets_svc.fulfill_request(
            db, decision=decision, plaintext=body.value, user_id=user.id
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    if resumed_task_id is not None:
        await enqueue_task(resumed_task_id)

    name = secrets_svc.normalize_name(str((decision.payload or {}).get("name") or ""))
    secret = await db.scalar(
        select(secrets_svc.Secret).where(
            secrets_svc.Secret.company_id == decision.company_id,
            secrets_svc.Secret.name == name,
            secrets_svc.Secret.status == secrets_svc.SecretStatus.active,
        )
    )
    return secret
