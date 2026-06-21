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


async def get_cloudflare(
    db: AsyncSession, *, company_id: uuid.UUID
) -> tuple[str, str] | None:
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


async def resolve_site_host(
    db: AsyncSession, *, company_id: uuid.UUID
) -> SiteHost | None:
    """The company's site host — enabled only when it has saved Cloudflare creds."""
    creds = await get_cloudflare(db, company_id=company_id)
    if creds is None:
        return None
    from app.integrations.cloudflare import CloudflareSiteHost

    return CloudflareSiteHost(token=creds[0], account_id=creds[1])


async def resolve_dns_provider(
    db: AsyncSession, *, company_id: uuid.UUID
) -> DnsProvider | None:
    """The company's DNS provider — enabled only when it has saved Cloudflare creds."""
    creds = await get_cloudflare(db, company_id=company_id)
    if creds is None:
        return None
    from app.integrations.cloudflare import CloudflareDns

    return CloudflareDns(token=creds[0], account_id=creds[1])


# ─────────────────────────── Google Drive (files) ───────────────────────────


async def set_google_drive(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    root_folder_id: str | None = None,
) -> None:
    """Store the company's Google OAuth bundle (whole JSON envelope-encrypted)."""
    payload = json.dumps(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "root_folder_id": root_folder_id or "root",
        }
    )
    await apikeys.store_key(db, company_id=company_id, provider=_GOOGLE_DRIVE, plaintext=payload)


async def get_google_drive(db: AsyncSession, *, company_id: uuid.UUID) -> dict | None:
    """Return the company's stored Google Drive OAuth bundle, or ``None`` if unset."""
    raw = await apikeys.get_plaintext_key(db, company_id=company_id, provider=_GOOGLE_DRIVE)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        # Require the three secrets; anything else (root_folder_id) is optional.
        for field in ("client_id", "client_secret", "refresh_token"):
            if not data.get(field):
                return None
        return data
    except ValueError:
        return None


async def google_drive_status(db: AsyncSession, *, company_id: uuid.UUID) -> dict:
    """UI-safe status: whether Drive is configured (never returns the secrets)."""
    creds = await get_google_drive(db, company_id=company_id)
    if creds is None:
        return {"configured": False, "root_folder_id": None}
    return {"configured": True, "root_folder_id": creds.get("root_folder_id") or "root"}


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
    credentials. ``ensure_folder([])`` is the cheapest valid call: it forces a token
    refresh and returns the store root without creating anything.
    """
    from app.integrations.gdrive import GoogleDriveFileProvider

    provider = GoogleDriveFileProvider(
        client_id=client_id,
        client_secret=client_secret,
        refresh_token=refresh_token,
        root_folder_id=root_folder_id or "root",
    )
    await provider.ensure_folder([])


async def resolve_file_provider(db: AsyncSession, *, company_id: uuid.UUID) -> FileProvider | None:
    """The company's file store — enabled only when it has connected Google Drive.

    Bring-your-own, like the site host: with no saved OAuth bundle this returns
    ``None`` so the file tools report the capability is unsupported rather than
    pretending a document was filed.
    """
    creds = await get_google_drive(db, company_id=company_id)
    if creds is None:
        return None
    from app.integrations.gdrive import GoogleDriveFileProvider

    return GoogleDriveFileProvider(
        client_id=creds["client_id"],
        client_secret=creds["client_secret"],
        refresh_token=creds["refresh_token"],
        root_folder_id=creds.get("root_folder_id") or "root",
    )
