"""TEMPORARY dev-only endpoints. Remove this whole module before going live.

Gated behind ``settings.dev_tools_enabled`` (env ``ABOS_DEV_TOOLS_ENABLED``) so
the surface can be killed without a code change. These exist only to make
iterating during development fast:

- ``GET  /dev/status``          — is the dev toolkit on? (drives the dev UI)
- ``POST /dev/default-login``   — auto-login as a fixed default account
- ``POST /dev/delete-all-accounts`` — wipe every account EXCEPT the default one

They are deliberately destructive / unauthenticated. Do not ship to production.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select

from app.config import settings
from app.deps import DbDep
from app.models import User
from app.schemas import TokenResponse
from app.security import create_access_token, hash_password

router = APIRouter(prefix="/dev", tags=["dev"])


def _require_enabled() -> None:
    if not settings.dev_tools_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dev tools are disabled.")


@router.get("/status")
async def status_() -> dict:
    """Whether the dev toolkit is enabled (always 200, so the UI can branch)."""
    return {
        "enabled": settings.dev_tools_enabled,
        "default_email": settings.dev_default_email if settings.dev_tools_enabled else None,
    }


@router.post("/default-login", response_model=TokenResponse)
async def default_login(db: DbDep) -> TokenResponse:
    """Get a token for the fixed default account, creating it on first use.

    Lets us skip the signup/login dance while developing — the frontend can
    auto-login and jump straight into onboarding or the dashboard.
    """
    _require_enabled()
    user = await db.scalar(select(User).where(User.email == settings.dev_default_email))
    if user is None:
        user = User(
            email=settings.dev_default_email,
            hashed_password=hash_password("dev-default-account"),
        )
        db.add(user)
        await db.commit()
    return TokenResponse(access_token=create_access_token(user.id))


@router.post("/galaxia/reset")
async def galaxia_reset(db: DbDep) -> dict:
    """Re-provision Galaxia from fleet creation, preserving saved BYOK keys.

    For the heavily-developed phase: wipes Galaxia's generated state (fleet,
    mission, objectives, runs, memory) and rebuilds it fresh from config, while
    saved provider keys survive — so you don't re-enter the model key each time.

    TEMP dev tool — do not ship to production.
    """
    _require_enabled()
    from app.services.galaxia import reset_galaxia

    company_id = await reset_galaxia(db)
    await db.commit()
    return {"reset": True, "company_id": str(company_id)}


@router.post("/delete-all-accounts")
async def delete_all_accounts(db: DbDep) -> dict:
    """Delete every account EXCEPT the default one, plus all data it owns.

    Deleting users cascades (ON DELETE CASCADE): users -> companies (owner) and
    memberships -> every tenant table keyed by ``company_id``. The default
    account (and its businesses) is preserved so we stay logged in. Marketplace
    seed data (global, not owned by a user) is left intact.

    TEMP dev tool — do not ship to production.
    """
    _require_enabled()
    keep = settings.dev_default_email
    count = await db.scalar(
        select(func.count()).select_from(User).where(User.email != keep)
    )
    await db.execute(delete(User).where(User.email != keep))
    await db.commit()
    return {"deleted_accounts": int(count or 0)}
