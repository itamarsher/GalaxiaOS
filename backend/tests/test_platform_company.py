"""The operator (dogfooding) company: config-based designation + the promoter gate.

The operator company is no longer a magic ``is_platform`` flag on a row — it's an
explicit ``ABOS_PLATFORM_COMPANY_ID`` naming a normal company. These tests cover the
config resolution, the promoter gate that follows it, that a company reset can't
change it (it's config, not company state), and account-wide Drive.
"""

from __future__ import annotations

import base64
import os
import uuid

from app.config import settings
from app.models import Budget, Company, User
from app.models.enums import BudgetPeriod, CompanyStatus
from app.runtime.tools.platform import _is_abos_admin_company
from app.services import company_reset, platform_company, user_drive
from tests.conftest import make_company_with_fleet, requires_db


def _set_master_key() -> None:
    settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


async def _bare_company(db) -> Company:
    user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(owner_user_id=user.id, name="C", status=CompanyStatus.draft)
    db.add(company)
    await db.flush()
    return company


@requires_db
async def test_operator_company_follows_config(session_factory):
    """``platform_company_id`` / ``is_platform_company`` reflect the config setting."""
    async with session_factory() as db:
        op = await _bare_company(db)
        tenant = await _bare_company(db)
        await db.commit()
        op_id, tenant_id = op.id, tenant.id

    # Unset (the default via the autouse reset): no operator company.
    settings.platform_company_id = ""
    assert platform_company.platform_company_id() is None
    assert platform_company.is_platform_company(op_id) is False

    # Configured: exactly that company is the operator; every other is a tenant.
    settings.platform_company_id = str(op_id)
    assert platform_company.platform_company_id() == op_id
    assert platform_company.is_platform_company(op_id) is True
    assert platform_company.is_platform_company(tenant_id) is False

    # Garbage config never raises — it just means "no operator".
    settings.platform_company_id = "not-a-uuid"
    assert platform_company.platform_company_id() is None
    assert platform_company.is_platform_company(op_id) is False


@requires_db
async def test_promoter_gate_follows_config(session_factory):
    async with session_factory() as db:
        op = await _bare_company(db)
        tenant = await _bare_company(db)
        await db.commit()
        op_id, tenant_id = op.id, tenant.id

    settings.platform_company_id = str(op_id)
    assert _is_abos_admin_company(op_id) is True
    assert _is_abos_admin_company(tenant_id) is False


@requires_db
async def test_reset_does_not_change_operator_designation(session_factory):
    """Operator status is config, not company state — a factory reset can't touch it."""
    async with session_factory() as db:
        cid = await make_company_with_fleet(db, is_platform=True)  # sets the config
        await db.commit()

    async with session_factory() as db:
        company = await db.get(Company, cid)
        await company_reset.reset_company(db, company=company)
        await db.commit()

    assert platform_company.is_platform_company(cid) is True  # config is unchanged


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
