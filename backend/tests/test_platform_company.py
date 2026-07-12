"""The platform-company flag: designation, the promoter gate, and account-wide Drive.

Replaces the old fixed-founder Galaxia bootstrap gate. The first onboarded company
is designated the platform company; the promoter tools authorize off that flag; and
a founder's Google Drive is stored account-wide on the user.
"""

from __future__ import annotations

import base64
import os
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.models import Budget, Company, User
from app.models.enums import BudgetPeriod, CompanyStatus
from app.runtime.tools.platform import _is_abos_admin_company
from app.services import platform_company, user_drive
from tests.conftest import make_company_with_fleet, requires_db


def _set_master_key() -> None:
    settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


async def _bare_company(db, *, is_platform=False) -> Company:
    user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(
        owner_user_id=user.id, name="C", status=CompanyStatus.draft, is_platform=is_platform
    )
    db.add(company)
    await db.flush()
    return company


@requires_db
async def test_designate_if_first_flags_only_the_first_company(session_factory):
    async with session_factory() as db:
        first = await _bare_company(db)
        assert await platform_company.designate_if_first(db, first) is True
        assert first.is_platform is True

        # A second company is an ordinary tenant.
        second = await _bare_company(db)
        assert await platform_company.designate_if_first(db, second) is False
        assert second.is_platform is False
        await db.commit()

        assert await platform_company.platform_company_id(db) == first.id


@requires_db
async def test_only_one_platform_company_allowed(session_factory):
    """The partial-unique index is the hard backstop against two platform companies."""
    async with session_factory() as db:
        await _bare_company(db, is_platform=True)
        # The second platform company violates the partial-unique index — the flush
        # is where asyncpg raises it.
        with pytest.raises(IntegrityError):
            await _bare_company(db, is_platform=True)


@requires_db
async def test_promoter_gate_keys_off_the_platform_flag(session_factory):
    async with session_factory() as db:
        platform_cid = await make_company_with_fleet(db, is_platform=True)
        tenant = await _bare_company(db, is_platform=False)
        await db.commit()
        tenant_id = tenant.id

    async with session_factory() as db:
        assert await _is_abos_admin_company(db, platform_cid) is True
        assert await _is_abos_admin_company(db, tenant_id) is False


@requires_db
async def test_account_wide_drive_round_trip(session_factory):
    _set_master_key()
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="C", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=1000))
        await db.commit()
        uid, cid = user.id, company.id

    # Nothing connected yet.
    async with session_factory() as db:
        assert await user_drive.get_user_drive(db, user_id=uid) is None
        status = await user_drive.user_drive_status(db, user_id=uid)
        assert status["configured"] is False

    # Store a token; it decrypts back and resolves for the owner's company.
    async with session_factory() as db:
        await user_drive.set_user_drive_refresh(db, user_id=uid, refresh_token="rt-secret")
        await db.commit()
    async with session_factory() as db:
        bundle = await user_drive.get_user_drive(db, user_id=uid)
        assert bundle is not None and bundle["refresh_token"] == "rt-secret"
        via_company = await user_drive.get_user_drive_for_company(db, company_id=cid)
        assert via_company is not None and via_company["refresh_token"] == "rt-secret"

    # Disconnect clears it.
    async with session_factory() as db:
        assert await user_drive.clear_user_drive(db, user_id=uid) is True
        await db.commit()
    async with session_factory() as db:
        assert await user_drive.get_user_drive(db, user_id=uid) is None
