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
