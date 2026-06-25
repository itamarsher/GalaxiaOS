"""Per-company integration credentials and provider resolution.

Today this is the **Cloudflare** credential pair (API token + account id) that
powers both the site-host and DNS seams. The token is a secret, so it is stored
through the same envelope-encrypted :class:`~app.models.apikey.ApiKey` store as the
other BYO keys (``provider="cloudflare"``); the non-secret account id rides along in
the encrypted JSON payload. Hosting/DNS is **bring-your-own-key**: the runtime
resolves a per-company adapter only when that company has saved its own credentials,
and returns ``None`` otherwise — so a company without a key reports the capability is
unsupported rather than faking a result. There is no platform-wide fallback.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.dns import DnsProvider
from app.integrations.files import FileProvider
from app.integrations.sitehost import SiteHost
from app.services import apikeys

_CLOUDFLARE = "cloudflare"
#: BYO key slot under which a company's Google Drive OAuth bundle is stored.
_GOOGLE_DRIVE = "google_drive"


async def set_cloudflare(
    db: AsyncSession, *, company_id: uuid.UUID, api_token: str, account_id: str
) -> None:
    """Store the company's Cloudflare credentials (token encrypted, account id with it)."""
    payload = json.dumps({"api_token": api_token, "account_id": account_id})
    await apikeys.store_key(db, company_id=company_id, provider=_CLOUDFLARE, plaintext=payload)


async def get_cloudflare(db: AsyncSession, *, company_id: uuid.UUID) -> tuple[str, str] | None:
    """Return ``(api_token, account_id)`` for the company, or ``None`` if unset."""
    raw = await apikeys.get_plaintext_key(db, company_id=company_id, provider=_CLOUDFLARE)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return str(data["api_token"]), str(data["account_id"])
    except (ValueError, KeyError):
        return None


async def cloudflare_status(db: AsyncSession, *, company_id: uuid.UUID) -> dict:
    """UI-safe status: whether it's configured and the (non-secret) account id."""
    creds = await get_cloudflare(db, company_id=company_id)
    if creds is None:
        return {"configured": False, "account_id": None}
    return {"configured": True, "account_id": creds[1]}


async def clear_cloudflare(db: AsyncSession, *, company_id: uuid.UUID) -> bool:
    """Revoke the company's stored Cloudflare credentials, if any."""
    from sqlalchemy import select

    from app.models import ApiKey
    from app.models.enums import ApiKeyStatus

    row = await db.scalar(
        select(ApiKey).where(
            ApiKey.company_id == company_id,
            ApiKey.provider == _CLOUDFLARE,
            ApiKey.status == ApiKeyStatus.active,
        )
    )
    if row is None:
        return False
    return await apikeys.revoke_key(db, company_id=company_id, key_id=row.id)


async def resolve_site_host(db: AsyncSession, *, company_id: uuid.UUID) -> SiteHost | None:
    """The company's site host — enabled only when it has saved Cloudflare creds."""
    creds = await get_cloudflare(db, company_id=company_id)
    if creds is None:
        return None
    from app.integrations.cloudflare import CloudflareSiteHost

    return CloudflareSiteHost(token=creds[0], account_id=creds[1])


async def resolve_dns_provider(db: AsyncSession, *, company_id: uuid.UUID) -> DnsProvider | None:
    """The company's DNS provider — enabled only when it has saved Cloudflare creds."""
    creds = await get_cloudflare(db, company_id=company_id)
    if creds is None:
        return None
    from app.integrations.cloudflare import CloudflareDns

    return CloudflareDns(token=creds[0], account_id=creds[1])


# ─────────────────────────── Google Drive (files) ───────────────────────────


async def set_google_drive_refresh(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    refresh_token: str,
    root_folder_id: str | None = None,
) -> None:
    """Store the company's Drive refresh token (envelope-encrypted JSON).

    Only the per-company ``refresh_token`` (and an optional ``root_folder_id``) is
    saved here; the OAuth ``client_id`` / ``client_secret`` belong to the
    deployment's Google app (config), so they are not stored per company.
    """
    payload = json.dumps(
        {"refresh_token": refresh_token, "root_folder_id": root_folder_id or "root"}
    )
    await apikeys.store_key(db, company_id=company_id, provider=_GOOGLE_DRIVE, plaintext=payload)


async def get_google_drive(db: AsyncSession, *, company_id: uuid.UUID) -> dict | None:
    """Return the company's stored Drive bundle, or ``None`` if unset/invalid.

    Only the ``refresh_token`` is required. Legacy bundles may also carry their own
    ``client_id`` / ``client_secret`` (from the old paste-the-secrets flow); those
    still resolve, falling back to the deployment app only when absent.
    """
    raw = await apikeys.get_plaintext_key(db, company_id=company_id, provider=_GOOGLE_DRIVE)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get("refresh_token"):
        return None
    return data


async def google_drive_status(db: AsyncSession, *, company_id: uuid.UUID) -> dict:
    """UI-safe status: whether Drive is connected (never returns the secrets) and
    whether one-click connect is available on this deployment."""
    from app.integrations import gdrive_oauth

    creds = await get_google_drive(db, company_id=company_id)
    return {
        "configured": creds is not None,
        "root_folder_id": (creds or {}).get("root_folder_id") or "root" if creds else None,
        "connect_available": gdrive_oauth.connect_configured(),
    }


async def complete_google_drive_oauth(
    db: AsyncSession, *, company_id: uuid.UUID, code: str, redirect_uri: str
) -> None:
    """Finish the Connect flow: trade ``code`` for a refresh token, verify, store.

    Verifying before persisting (one token refresh + reaching the store root)
    means a bundle that wouldn't actually work is never saved.
    """
    from app.config import settings
    from app.integrations import gdrive_oauth

    refresh_token = await gdrive_oauth.exchange_code_for_refresh_token(
        code=code, redirect_uri=redirect_uri
    )
    await verify_google_drive(
        client_id=settings.google_oauth_client_id,
        client_secret=settings.google_oauth_client_secret,
        refresh_token=refresh_token,
    )
    await set_google_drive_refresh(db, company_id=company_id, refresh_token=refresh_token)


async def clear_google_drive(db: AsyncSession, *, company_id: uuid.UUID) -> bool:
    """Revoke the company's stored Google Drive credentials, if any."""
    from sqlalchemy import select

    from app.models import ApiKey
    from app.models.enums import ApiKeyStatus

    row = await db.scalar(
        select(ApiKey).where(
            ApiKey.company_id == company_id,
            ApiKey.provider == _GOOGLE_DRIVE,
            ApiKey.status == ApiKeyStatus.active,
        )
    )
    if row is None:
        return False
    return await apikeys.revoke_key(db, company_id=company_id, key_id=row.id)


async def verify_google_drive(
    *, client_id: str, client_secret: str, refresh_token: str, root_folder_id: str = "root"
) -> None:
    """Prove an OAuth bundle works before it's saved (refresh token + reach root).

    Raises :class:`~app.integrations.files.FileProviderError` if Google rejects the
    credentials. ``check_access()`` is the cheapest call that actually validates: a
    real ``files.list`` that forces a refresh-token exchange and confirms Drive is
    reachable, without creating anything. It must be scope-safe — the ``drive.file``
    scope forbids reading My Drive root metadata — so a list (not a root GET) is
    used. (An empty ``ensure_folder([])`` would make no request at all, so it
    couldn't catch a bad token.)
    """
    from app.integrations.gdrive import GoogleDriveFileProvider

    provider = GoogleDriveFileProvider(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        root_folder_id=root_folder_id or "root",
    )
    await provider.check_access()


async def _owner_google_drive(company_id: uuid.UUID) -> dict | None:
    """Fall back to a Drive the same FOUNDER connected on another of their companies.

    A founder's Google Drive is their *personal* store: they connect it once and
    reasonably expect every business they launch to file into it. But each launched
    business is its own ``Company`` (and Drive credentials are stored per company),
    so a business that didn't do the connecting itself has no bundle — which is why
    its agents see ``save_file`` as "not connected" even though the founder linked
    Drive on a sibling company.

    This finds the most recent active Drive bundle among the companies owned by the
    SAME user. It runs on a fresh, non-tenant-scoped session on purpose: the caller's
    session is RLS-pinned to its own company and cannot see a sibling company's rows.
    The lookup is still strictly scoped to the same ``owner_user_id``, so it never
    reaches another founder's credentials.
    """
    from sqlalchemy import select

    from app.crypto import envelope
    from app.db import SessionLocal
    from app.models import ApiKey, Company
    from app.models.enums import ApiKeyStatus

    async with SessionLocal() as s:
        owner_id = await s.scalar(select(Company.owner_user_id).where(Company.id == company_id))
        if owner_id is None:
            return None
        row = await s.scalar(
            select(ApiKey)
            .join(Company, ApiKey.company_id == Company.id)
            .where(
                Company.owner_user_id == owner_id,
                ApiKey.provider == _GOOGLE_DRIVE,
                ApiKey.status == ApiKeyStatus.active,
            )
            .order_by(ApiKey.created_at.desc())
            .limit(1)
        )
        if row is None:
            return None
        raw = envelope.open_secret(
            envelope.SealedSecret(
                ciphertext=row.encrypted_key,
                wrapped_data_key=row.encrypted_data_key,
                nonce=row.nonce,
            )
        )
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if data.get("refresh_token") else None


async def resolve_file_provider(db: AsyncSession, *, company_id: uuid.UUID) -> FileProvider | None:
    """The company's file store — enabled when this company, or its founder on a
    sibling company, has connected Google Drive.

    Bring-your-own, like the site host: with no saved OAuth bundle anywhere for the
    founder this returns ``None`` so the file tools report the capability is
    unsupported rather than pretending a document was filed. The founder-level
    fallback means connecting Drive once covers every business they launch, instead
    of silently only working for the one company that did the connecting.
    """
    creds = await get_google_drive(db, company_id=company_id)
    if creds is None:
        # This business didn't connect Drive itself — use the founder's Drive
        # connected on another of their companies, if any.
        creds = await _owner_google_drive(company_id)
    if creds is None:
        return None
    from app.config import settings
    from app.integrations.gdrive import GoogleDriveFileProvider

    return GoogleDriveFileProvider(
        # New bundles store only the refresh token and use the deployment's OAuth
        # app; legacy bundles carry their own client_id/secret, which win when set.
        client_id=creds.get("client_id") or settings.google_oauth_client_id,
        client_secret=creds.get("client_secret") or settings.google_oauth_client_secret,
        refresh_token=creds["refresh_token"],
        root_folder_id=creds.get("root_folder_id") or "root",
    )
