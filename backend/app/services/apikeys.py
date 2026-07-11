"""BYOK provider-key storage and retrieval.

Plaintext keys exist only transiently here and inside the provider layer. The
DB stores ciphertext + a wrapped data key + a display fingerprint.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import envelope
from app.models import ApiKey
from app.models.enums import ApiKeyStatus
from app.providers.base import LLMProvider
from app.providers.registry import get_provider, supported_providers


async def store_key(
    db: AsyncSession, *, company_id: uuid.UUID, provider: str, plaintext: str
) -> ApiKey:
    """Encrypt and persist a provider key, replacing any active key for the provider."""
    existing = await db.scalars(
        select(ApiKey).where(
            ApiKey.company_id == company_id,
            ApiKey.provider == provider,
            ApiKey.status == ApiKeyStatus.active,
        )
    )
    for old in existing:
        old.status = ApiKeyStatus.revoked

    sealed = envelope.seal(plaintext)
    key = ApiKey(
        company_id=company_id,
        provider=provider,
        encrypted_key=sealed.ciphertext,
        encrypted_data_key=sealed.wrapped_data_key,
        nonce=sealed.nonce,
        key_fingerprint=envelope.fingerprint(plaintext),
        status=ApiKeyStatus.active,
    )
    db.add(key)
    await db.flush()
    return key


async def get_plaintext_key(
    db: AsyncSession, *, company_id: uuid.UUID, provider: str
) -> str | None:
    """Decrypt the active provider key. The result must never be logged or stored."""
    row = await db.scalar(
        select(ApiKey).where(
            ApiKey.company_id == company_id,
            ApiKey.provider == provider,
            ApiKey.status == ApiKeyStatus.active,
        )
    )
    if row is None:
        return None
    sealed = envelope.SealedSecret(
        ciphertext=row.encrypted_key,
        wrapped_data_key=row.encrypted_data_key,
        nonce=row.nonce,
    )
    return envelope.open_secret(sealed)


async def has_active_key(db: AsyncSession, *, company_id: uuid.UUID, provider: str) -> bool:
    """True if the company has an active key for ``provider`` (no decryption)."""
    row = await db.scalar(
        select(ApiKey.id).where(
            ApiKey.company_id == company_id,
            ApiKey.provider == provider,
            ApiKey.status == ApiKeyStatus.active,
        )
    )
    return row is not None


async def list_keys(db: AsyncSession, *, company_id: uuid.UUID) -> list[ApiKey]:
    rows = await db.scalars(
        select(ApiKey).where(ApiKey.company_id == company_id, ApiKey.status == ApiKeyStatus.active)
    )
    return list(rows)


async def revoke_key(db: AsyncSession, *, company_id: uuid.UUID, key_id: uuid.UUID) -> bool:
    """Revoke a single active key (so the founder can remove/rotate it). Tenant-scoped.

    Returns ``False`` if there's no active key with that id for the company (already
    revoked or never existed), so the delete endpoint can 404 rather than no-op.
    """
    row = await db.scalar(
        select(ApiKey).where(
            ApiKey.id == key_id,
            ApiKey.company_id == company_id,
            ApiKey.status == ApiKeyStatus.active,
        )
    )
    if row is None:
        return False
    row.status = ApiKeyStatus.revoked
    await db.flush()
    return True


async def get_active_key(db: AsyncSession, *, company_id: uuid.UUID) -> ApiKey | None:
    """The company's active key for a *supported* provider (most recent first)."""
    rows = await db.scalars(
        select(ApiKey)
        .where(ApiKey.company_id == company_id, ApiKey.status == ApiKeyStatus.active)
        .order_by(ApiKey.created_at.desc())
    )
    supported = set(supported_providers())
    for key in rows:
        if key.provider in supported:
            return key
    return None


async def resolve_provider(
    db: AsyncSession, *, company_id: uuid.UUID
) -> tuple[LLMProvider, str] | None:
    """Resolve the company's (provider, plaintext key) from its stored BYOK key.

    This is what makes BYOK provider-agnostic: the provider is chosen by which
    key the founder configured, not hardcoded. Returns ``None`` if no usable key.

    This is the low-level BYO-only lookup; callers that should fall back to the
    platform key under managed mode use :func:`resolve_active_provider` instead.
    """
    key = await get_active_key(db, company_id=company_id)
    if key is None:
        return None
    sealed = envelope.SealedSecret(
        ciphertext=key.encrypted_key,
        wrapped_data_key=key.encrypted_data_key,
        nonce=key.nonce,
    )
    return get_provider(key.provider), envelope.open_secret(sealed)


@dataclass(frozen=True)
class ResolvedProvider:
    """A resolved LLM credential plus who is funding it.

    ``source`` is ``"byo"`` (the founder's own stored key — never metered against
    the platform allowance) or ``"platform"`` (the shared managed key). For a
    platform key, ``funding_user_id`` is the founder to bill; pass it straight to
    ``CostMeter.run_llm(..., funding_user_id=...)`` so the spend lands on their
    allowance. It is ``None`` for a BYO key (nothing to meter against the platform).
    """

    provider: LLMProvider
    api_key: str
    source: str  # "byo" | "platform"
    provider_name: str
    funding_user_id: uuid.UUID | None = None


async def resolve_active_provider(
    db: AsyncSession, *, company_id: uuid.UUID
) -> ResolvedProvider | None:
    """The LLM a company should think with: its own key first, else the platform's.

    A founder's stored BYOK key always wins. Otherwise, when managed mode is on,
    a configured platform key is offered — but only if the founder is still
    eligible (within their free allowance / daily cap, or on the paid tier).
    Returns ``None`` when neither is available (no BYOK and managed unavailable or
    the founder is over their cap), leaving the "add a key / upgrade" decision to
    the caller.
    """
    byo = await resolve_provider(db, company_id=company_id)
    if byo is not None:
        provider, api_key = byo
        return ResolvedProvider(provider, api_key, "byo", provider.name)

    # No BYOK — try the platform key under managed mode.
    from app.services import billing

    if not await billing.platform_llm_configured():
        return None
    elig = await billing.platform_available(db, company_id=company_id)
    if not elig.allowed:
        return None
    try:
        provider = get_provider(settings.platform_llm_provider)
    except ValueError:
        return None
    owner_id = await billing.owner_of(db, company_id=company_id)
    return ResolvedProvider(
        provider,
        settings.platform_llm_api_key,
        "platform",
        settings.platform_llm_provider,
        funding_user_id=owner_id,
    )
