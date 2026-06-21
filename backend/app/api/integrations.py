"""Per-company integration credentials (Cloudflare site host + DNS).

The API token is stored envelope-encrypted (never returned); the non-secret account
id is shown back so the founder can confirm it. Saving verifies the credentials
against Cloudflare so a bad token/account is rejected up front.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.deps import CompanyDep, DbDep
from app.integrations.cloudflare import verify_credentials
from app.integrations.files import FileProviderError
from app.integrations.sitehost import SiteHostError
from app.schemas import (
    CloudflareCredsRequest,
    CloudflareStatusOut,
    GoogleDriveCredsRequest,
    GoogleDriveStatusOut,
)
from app.services import integrations as integrations_svc

router = APIRouter(prefix="/companies/{company_id}/integrations", tags=["integrations"])


@router.get("/cloudflare", response_model=CloudflareStatusOut)
async def cloudflare_status(company: CompanyDep, db: DbDep):
    return await integrations_svc.cloudflare_status(db, company_id=company.id)


@router.put("/cloudflare", response_model=CloudflareStatusOut)
async def set_cloudflare(company: CompanyDep, body: CloudflareCredsRequest, db: DbDep):
    try:
        await verify_credentials(body.api_token.strip(), body.account_id.strip())
    except SiteHostError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Cloudflare rejected these credentials: {exc}"
        ) from exc
    await integrations_svc.set_cloudflare(
        db, company_id=company.id, api_token=body.api_token.strip(), account_id=body.account_id.strip()
    )
    await db.commit()
    return await integrations_svc.cloudflare_status(db, company_id=company.id)


@router.delete("/cloudflare", status_code=status.HTTP_204_NO_CONTENT)
async def clear_cloudflare(company: CompanyDep, db: DbDep):
    removed = await integrations_svc.clear_cloudflare(db, company_id=company.id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Cloudflare credentials configured")
    await db.commit()


# ─────────────────────────── Google Drive (file store) ───────────────────────────


@router.get("/google-drive", response_model=GoogleDriveStatusOut)
async def google_drive_status(company: CompanyDep, db: DbDep):
    return await integrations_svc.google_drive_status(db, company_id=company.id)


@router.put("/google-drive", response_model=GoogleDriveStatusOut)
async def set_google_drive(company: CompanyDep, body: GoogleDriveCredsRequest, db: DbDep):
    # Verify the OAuth bundle works before saving it: refresh once + resolve the
    # store root, so a bad client/secret/refresh-token is rejected up front rather
    # than failing silently the first time an agent tries to file a document.
    try:
        await integrations_svc.verify_google_drive(
            client_id=body.client_id.strip(),
            client_secret=body.client_secret.strip(),
            refresh_token=body.refresh_token.strip(),
            root_folder_id=(body.root_folder_id or "").strip() or "root",
        )
    except FileProviderError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Google rejected these credentials: {exc}"
        ) from exc
    await integrations_svc.set_google_drive(
        db,
        company_id=company.id,
        client_id=body.client_id.strip(),
        client_secret=body.client_secret.strip(),
        refresh_token=body.refresh_token.strip(),
        root_folder_id=(body.root_folder_id or "").strip() or "root",
    )
    await db.commit()
    return await integrations_svc.google_drive_status(db, company_id=company.id)


@router.delete("/google-drive", status_code=status.HTTP_204_NO_CONTENT)
async def clear_google_drive(company: CompanyDep, db: DbDep):
    removed = await integrations_svc.clear_google_drive(db, company_id=company.id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Google Drive credentials configured")
    await db.commit()
