"""FastAPI dependencies: authentication and tenant-scoped company access."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Company, Membership, User
from app.security import decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

DbDep = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbDep, token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_company_for_user(
    company_id: uuid.UUID, db: DbDep, user: CurrentUser
) -> Company:
    """Resolve a company the caller is a member of, or 404/403.

    This is the enforcement point for the ``company_id`` tenant boundary: a
    company is only reachable through a membership owned by the current user.
    """
    membership = await db.scalar(
        select(Membership).where(
            Membership.company_id == company_id, Membership.user_id == user.id
        )
    )
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Company not found")
    return company


CompanyDep = Annotated[Company, Depends(get_company_for_user)]
