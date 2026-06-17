"""TEMPORARY dev-only endpoints. Remove this whole module before going live.

Gated behind ``settings.dev_tools_enabled`` (env ``ABOS_DEV_TOOLS_ENABLED``) so
it can be killed without a code change. The single endpoint here wipes ALL
accounts and their data — it exists only to make iterating during development
fast, and is deliberately destructive and unauthenticated.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, func, select

from app.config import settings
from app.deps import DbDep
from app.models import User

router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/delete-all-accounts")
async def delete_all_accounts(db: DbDep):
    """Delete every user account and all data that hangs off it.

    Deleting users cascades (ON DELETE CASCADE): users -> companies (owner) and
    memberships -> every tenant table keyed by ``company_id``. Marketplace seed
    data (global, not owned by a user) is left intact.

    TEMP dev tool — do not ship to production.
    """
    if not settings.dev_tools_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Dev tools are disabled.")

    count = await db.scalar(select(func.count()).select_from(User))
    await db.execute(delete(User))
    await db.commit()
    return {"deleted_accounts": int(count or 0)}
