"""TEMP dev reset endpoint — delete all accounts (cascades to all data).

Remove alongside app/api/dev.py before launch.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.dev import delete_all_accounts
from app.models import Company, User
from tests.conftest import requires_db


@requires_db
async def test_delete_all_accounts_wipes_users_and_cascades(
    session_factory, company_with_budget
):
    # company_with_budget created a user + company (+ budget).
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) >= 1
        assert await db.scalar(select(func.count()).select_from(Company)) >= 1

    async with session_factory() as db:
        result = await delete_all_accounts(db)
    assert result["deleted_accounts"] >= 1

    # Deleting users cascades to their companies (owner FK) and all tenant data.
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(User)) == 0
        assert await db.scalar(select(func.count()).select_from(Company)) == 0


@requires_db
async def test_delete_all_accounts_respects_kill_switch(session_factory, monkeypatch):
    from app.api import dev as dev_module

    monkeypatch.setattr(dev_module.settings, "dev_tools_enabled", False)
    async with session_factory() as db:
        with pytest.raises(HTTPException) as exc:
            await delete_all_accounts(db)
    assert exc.value.status_code == 403
