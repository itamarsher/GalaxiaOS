"""Account-wide Google Drive: a per-user file store connected once.

A founder's Google Drive is their *personal* store; they connect it once and every
business they launch files into it. So — unlike the legacy per-company Drive
bundle stored under an :class:`~app.models.apikey.ApiKey` slot — the account-wide
refresh token lives on the :class:`~app.models.user.User`, envelope-encrypted with
the same scheme as a BYOK key (ciphertext + wrapped data key + nonce; plaintext is
never persisted).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import envelope
from app.models import User


async def set_user_drive_refresh(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    refresh_token: str,
    root_folder_id: str | None = None,
) -> None:
    """Store the user's account-wide Drive refresh token (envelope-encrypted)."""
    user = await db.get(User, user_id)
    if user is None:
        return
    sealed = envelope.seal(refresh_token)
    user.gdrive_refresh_ct = sealed.ciphertext
    user.gdrive_refresh_dek = sealed.wrapped_data_key
    user.gdrive_refresh_nonce = sealed.nonce
    user.gdrive_root_folder_id = root_folder_id or "root"
    await db.flush()


def _refresh_token_from_user(user: User) -> str | None:
    """Decrypt the user's stored Drive refresh token, or ``None`` if unset."""
    if not (user.gdrive_refresh_ct and user.gdrive_refresh_dek and user.gdrive_refresh_nonce):
        return None
    return envelope.open_secret(
        envelope.SealedSecret(
            ciphertext=user.gdrive_refresh_ct,
            wrapped_data_key=user.gdrive_refresh_dek,
            nonce=user.gdrive_refresh_nonce,
        )
    )


async def get_user_drive(db: AsyncSession, *, user_id: uuid.UUID) -> dict | None:
    """Return ``{"refresh_token", "root_folder_id"}`` for the user, or ``None``."""
    user = await db.get(User, user_id)
    if user is None:
        return None
    token = _refresh_token_from_user(user)
    if not token:
        return None
    return {"refresh_token": token, "root_folder_id": user.gdrive_root_folder_id or "root"}


async def get_user_drive_for_company(db: AsyncSession, *, company_id: uuid.UUID) -> dict | None:
    """The account-wide Drive bundle of the company's OWNER, if connected.

    Runs on a fresh, non-tenant-scoped session because the caller's session is
    RLS-pinned to its own company and cannot read the ``users`` row's owner across
    tenants. Strictly scoped to the company's own ``owner_user_id``, so it never
    reaches another founder's Drive.
    """
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Company

    async with SessionLocal() as s:
        owner_id = await s.scalar(
            select(Company.owner_user_id).where(Company.id == company_id)
        )
        if owner_id is None:
            return None
        return await get_user_drive(s, user_id=owner_id)


async def user_drive_status(db: AsyncSession, *, user_id: uuid.UUID) -> dict:
    """UI-safe status: whether the user connected Drive and whether connect is on."""
    from app.integrations import google_oauth

    bundle = await get_user_drive(db, user_id=user_id)
    return {
        "configured": bundle is not None,
        "root_folder_id": (bundle or {}).get("root_folder_id") if bundle else None,
        "connect_available": google_oauth.connect_configured(),
    }


async def clear_user_drive(db: AsyncSession, *, user_id: uuid.UUID) -> bool:
    """Disconnect the user's account-wide Drive. Returns whether anything was set."""
    user = await db.get(User, user_id)
    if user is None or not user.gdrive_refresh_ct:
        return False
    user.gdrive_refresh_ct = None
    user.gdrive_refresh_dek = None
    user.gdrive_refresh_nonce = None
    user.gdrive_root_folder_id = None
    await db.flush()
    return True
