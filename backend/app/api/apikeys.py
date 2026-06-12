"""BYOK provider-key endpoints. Responses expose fingerprints only, never plaintext."""

from __future__ import annotations

from fastapi import APIRouter

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
