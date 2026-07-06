"""Per-company integration credentials (Cloudflare site host + DNS).

The API token is stored envelope-encrypted (never returned); the non-secret account
id is shown back so the founder can confirm it. Saving verifies the credentials
against Cloudflare so a bad token/account is rejected up front.
"""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from app.config import settings
from app.db import set_tenant
from app.deps import CompanyDep, DbDep
from app.integrations import gdrive_oauth
from app.integrations.cloudflare import verify_credentials
from app.integrations.files import FileProviderError
from app.integrations.sitehost import SiteHostError
from app.schemas import (
    CloudflareCredsRequest,
    CloudflareStatusOut,
    GoogleDriveConnectOut,
    GoogleDriveStatusOut,
)
from app.security import create_oauth_state, decode_oauth_state
from app.services import integrations as integrations_svc

router = APIRouter(prefix="/companies/{company_id}/integrations", tags=["integrations"])

# The OAuth callback is hit by the founder's browser via Google's redirect, so it
# can't sit under the bearer-authenticated company prefix or carry a token. It
# lives at a fixed top-level path (the one registered on the OAuth client) and
# authenticates via the signed ``state`` instead.
callback_router = APIRouter(prefix="/integrations/google-drive", tags=["integrations"])


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
        db,
        company_id=company.id,
        api_token=body.api_token.strip(),
        account_id=body.account_id.strip(),
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


@router.post("/google-drive/connect", response_model=GoogleDriveConnectOut)
async def connect_google_drive(company: CompanyDep):
    """Begin one-click connect: return the Google consent URL to redirect to.

    The signed ``state`` carries this company's id so the (unauthenticated)
    callback can attribute the resulting refresh token without a bearer token.
    """
    if not gdrive_oauth.connect_configured():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Google Drive connect is not enabled on this deployment.",
        )
    url = gdrive_oauth.authorize_url(
        client_id=settings.google_oauth_client_id,
        redirect_uri=gdrive_oauth.redirect_uri(settings.public_api_base_url),
        state=create_oauth_state(company.id),
    )
    return {"authorize_url": url}


@router.delete("/google-drive", status_code=status.HTTP_204_NO_CONTENT)
async def clear_google_drive(company: CompanyDep, db: DbDep):
    removed = await integrations_svc.clear_google_drive(db, company_id=company.id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No Google Drive credentials configured")
    await db.commit()


def _settings_redirect(company_id: str, **params: str) -> RedirectResponse:
    """Bounce the founder's browser back to the company's Settings page."""
    base = f"{settings.web_base_url.rstrip('/')}/c/{company_id}/settings"
    return RedirectResponse(f"{base}?{urlencode(params)}", status_code=status.HTTP_303_SEE_OTHER)


@callback_router.get("/callback")
async def google_drive_callback(
    db: DbDep,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Google's redirect target: exchange the code for a refresh token and store it.

    Authenticated by the signed ``state`` (not a bearer token). On success or
    failure the founder is redirected back to Settings with a ``gdrive`` flag so
    the UI can show the outcome.
    """
    company_id = decode_oauth_state(state) if state else None
    if company_id is None:
        # Can't trust the state → no company to attribute or redirect to safely.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OAuth state.")
    if error or not code:
        # User declined consent, or Google returned no code.
        return _settings_redirect(str(company_id), gdrive=error or "denied")
    # Scope this write to the tenant the state names (the callback never went
    # through the company dependency that normally activates RLS).
    await set_tenant(db, company_id)
    try:
        await integrations_svc.complete_google_drive_oauth(
            db,
            company_id=company_id,
            code=code,
            redirect_uri=gdrive_oauth.redirect_uri(settings.public_api_base_url),
        )
    except FileProviderError:
        await db.rollback()
        return _settings_redirect(str(company_id), gdrive="error")
    await db.commit()
    return _settings_redirect(str(company_id), gdrive="connected")
