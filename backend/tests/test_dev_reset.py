"""TEMP dev toolkit — default-account auto-login + delete-all-but-default.

Remove alongside app/api/dev.py before launch.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.dev import default_login, delete_all_accounts
from app.config import settings
from app.models import Company, User
from tests.conftest import requires_db


@requires_db
async def test_delete_all_accounts_wipes_non_default_and_cascades(
    session_factory, company_with_budget
):
    # company_with_budget created a (non-default) user + company (+ budget).
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) >= 1
        assert await db.scalar(select(func.count()).select_from(Company)) >= 1

    async with session_factory() as db:
        result = await delete_all_accounts(db)
    assert result["deleted_accounts"] >= 1

    # No default account exists here, so everything is removed and cascades.
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 0
        assert await db.scalar(select(func.count()).select_from(Company)) == 0


@requires_db
async def test_default_login_creates_then_reuses_the_default_account(session_factory):
    async with session_factory() as db:
        tok1 = await default_login(db)
    async with session_factory() as db:
        tok2 = await default_login(db)
        n = await db.scalar(
            select(func.count()).select_from(User).where(User.email == settings.dev_default_email)
        )
    assert tok1.access_token and tok2.access_token
    assert n == 1  # created once, reused thereafter


@requires_db
async def test_delete_all_accounts_preserves_the_default(session_factory, company_with_budget):
    async with session_factory() as db:
        await default_login(db)  # ensure the default account exists alongside the normal one

    async with session_factory() as db:
        await delete_all_accounts(db)

    async with session_factory() as db:
        emails = (await db.scalars(select(User.email))).all()
    assert emails == [settings.dev_default_email]  # only the default survives


@requires_db
async def test_dev_endpoints_respect_kill_switch(session_factory, monkeypatch):
    from app.api import dev as dev_module

    monkeypatch.setattr(dev_module.settings, "dev_tools_enabled", False)
    async with session_factory() as db:
        for call in (default_login, delete_all_accounts):
            with pytest.raises(HTTPException) as exc:
                await call(db)
            assert exc.value.status_code == 403
