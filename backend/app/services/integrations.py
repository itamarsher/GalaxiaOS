"""Per-company integration credentials and provider resolution.

Today this is the **Cloudflare** credential pair (API token + account id) that
powers both the site-host and DNS seams. The token is a secret, so it is stored
through the same envelope-encrypted :class:`~app.models.apikey.ApiKey` store as the
other BYO keys (``provider="cloudflare"``); the non-secret account id rides along in
the encrypted JSON payload. The runtime resolves a per-company adapter at call time,
falling back to the ``ABOS_CLOUDFLARE_*`` env vars (a single platform account) and to
``None`` when nothing is configured — so an unconfigured company reports the
capability is unsupported rather than faking a result.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.dns import DnsProvider
from app.integrations.sitehost import SiteHost
from app.services import apikeys

_CLOUDFLARE = "cloudflare"


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


async def _cloudflare_creds(
    db: AsyncSession, company_id: uuid.UUID
) -> tuple[str, str] | None:
    """Per-company creds, falling back to the platform env vars."""
    creds = await get_cloudflare(db, company_id=company_id)
    if creds is not None:
        return creds
    if settings.cloudflare_api_token and settings.cloudflare_account_id:
        return settings.cloudflare_api_token, settings.cloudflare_account_id
    return None


async def resolve_site_host(
    db: AsyncSession, *, company_id: uuid.UUID
) -> SiteHost | None:
    """The company's site host, or ``None`` when hosting is off / unconfigured."""
    if settings.site_host == "none":
        return None
    if settings.site_host == "cloudflare":
        creds = await _cloudflare_creds(db, company_id)
        if creds is None:
            return None
        from app.integrations.cloudflare import CloudflareSiteHost

        return CloudflareSiteHost(token=creds[0], account_id=creds[1])
    from app.integrations.sitehost import get_site_host

    return get_site_host()


async def resolve_dns_provider(
    db: AsyncSession, *, company_id: uuid.UUID
) -> DnsProvider | None:
    """The company's DNS provider, or ``None`` when DNS is off / unconfigured."""
    if settings.dns_provider == "none":
        return None
    if settings.dns_provider == "cloudflare":
        creds = await _cloudflare_creds(db, company_id)
        if creds is None:
            return None
        from app.integrations.cloudflare import CloudflareDns

        return CloudflareDns(token=creds[0], account_id=creds[1])
    from app.integrations.dns import get_dns_provider

    return get_dns_provider()
