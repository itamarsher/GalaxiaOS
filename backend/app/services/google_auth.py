"""Google SSO account resolution: upsert a user from a verified Google identity."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.google_oauth import GoogleIdentity
from app.models import User


async def upsert_google_user(db: AsyncSession, identity: GoogleIdentity) -> User:
    """Get-or-create the user for a verified Google identity.

    Resolution order:

    1. By ``google_sub`` — the stable, immutable account key. If found, refresh the
       display name (and email, which can change on the Google side).
    2. By ``email`` — an existing account (e.g. created via email/password, or the
       founder's first company) claims its Google identity by linking ``google_sub``
       on first SSO. This is what lets the first password/dev account "become" an
       SSO account without losing its companies.
    3. Otherwise create a fresh SSO account (no local password).

    The caller commits.
    """
    user = await db.scalar(select(User).where(User.google_sub == identity.sub))
    if user is not None:
        user.email = identity.email
        if identity.name:
            user.name = identity.name
        await db.flush()
        return user

    user = await db.scalar(select(User).where(User.email == identity.email))
    if user is not None:
        user.google_sub = identity.sub
        if identity.name:
            user.name = identity.name
        await db.flush()
        return user

    user = User(
        email=identity.email,
        google_sub=identity.sub,
        name=identity.name,
        hashed_password=None,
    )
    db.add(user)
    await db.flush()
    return user
