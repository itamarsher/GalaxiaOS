"""BYOK provider-key storage and retrieval.

Plaintext keys exist only transiently here and inside the provider layer. The
DB stores ciphertext + a wrapped data key + a display fingerprint.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import envelope
from app.models import ApiKey
from app.models.enums import ApiKeyStatus


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


async def list_keys(db: AsyncSession, *, company_id: uuid.UUID) -> list[ApiKey]:
    rows = await db.scalars(
        select(ApiKey).where(
            ApiKey.company_id == company_id, ApiKey.status == ApiKeyStatus.active
        )
    )
    return list(rows)
