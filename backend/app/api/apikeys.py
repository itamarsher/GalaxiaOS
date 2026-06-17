"""BYOK provider-key endpoints. Responses expose fingerprints only, never plaintext."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.deps import CompanyDep, DbDep
from app.schemas import ApiKeyCreateRequest, ApiKeyOut
from app.services import apikeys

router = APIRouter(prefix="/companies/{company_id}/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyOut)
async def add_key(company: CompanyDep, body: ApiKeyCreateRequest, db: DbDep):
    key = await apikeys.store_key(
        db, company_id=company.id, provider=body.provider, plaintext=body.api_key
    )
    await db.commit()
    return key


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(company: CompanyDep, db: DbDep):
    return await apikeys.list_keys(db, company_id=company.id)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(company: CompanyDep, key_id: uuid.UUID, db: DbDep):
    removed = await apikeys.revoke_key(db, company_id=company.id, key_id=key_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Key not found")
    await db.commit()
