"""Managed-mode billing: platform-key fallback, free tier → blocked, ledger.

DB-backed (real rows + the ``platform_billing_accounts``/``platform_charges``
tables). Skipped unless ``ABOS_TEST_DATABASE_URL`` is set.
"""

from __future__ import annotations

import base64
import os
import uuid

from tests.conftest import requires_db

pytestmark = requires_db


def _set_master_key():
    from app.config import settings as app_settings

    if not app_settings.master_key:
        app_settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


async def _make_company(session_factory):
    from app.models import Budget, Company, User
    from app.models.enums import BudgetPeriod, CompanyStatus

    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=10_000))
        await db.commit()
        return company.id, user.id


def _managed_on(monkeypatch, *, free=200, daily=100):
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "managed_mode_enabled", True)
    monkeypatch.setattr(app_settings, "platform_llm_provider", "anthropic")
    monkeypatch.setattr(app_settings, "platform_llm_api_key", "sk-ant-platform")
    monkeypatch.setattr(app_settings, "platform_free_tier_cents", free)
    monkeypatch.setattr(app_settings, "platform_daily_cap_cents", daily)


async def test_platform_fallback_when_no_byo_key(session_factory, monkeypatch):
    _set_master_key()
    _managed_on(monkeypatch)
    cid, uid = await _make_company(session_factory)
    from app.services import apikeys

    async with session_factory() as db:
        resolved = await apikeys.resolve_active_provider(db, company_id=cid)
    assert resolved is not None
    assert resolved.source == "platform"
    assert resolved.provider.name == "anthropic"
    assert resolved.api_key == "sk-ant-platform"
    assert resolved.funding_user_id == uid


async def test_byo_key_wins_over_platform(session_factory, monkeypatch):
    _set_master_key()
    _managed_on(monkeypatch)
    cid, _ = await _make_company(session_factory)
    from app.services import apikeys

    async with session_factory() as db:
        await apikeys.store_key(db, company_id=cid, provider="anthropic", plaintext="sk-ant-mine")
        await db.commit()
        resolved = await apikeys.resolve_active_provider(db, company_id=cid)
    assert resolved is not None
    assert resolved.source == "byo"
    assert resolved.api_key == "sk-ant-mine"
    assert resolved.funding_user_id is None  # BYO is never metered to the platform


async def test_no_fallback_when_managed_off(session_factory, monkeypatch):
    _set_master_key()
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "managed_mode_enabled", False)
    cid, _ = await _make_company(session_factory)
    from app.services import apikeys

    async with session_factory() as db:
        resolved = await apikeys.resolve_active_provider(db, company_id=cid)
    assert resolved is None


async def test_no_fallback_when_platform_key_missing(session_factory, monkeypatch):
    _set_master_key()
    _managed_on(monkeypatch)
    from app.config import settings as app_settings

    monkeypatch.setattr(app_settings, "platform_llm_api_key", "")  # configured off
    cid, _ = await _make_company(session_factory)
    from app.services import apikeys

    async with session_factory() as db:
        resolved = await apikeys.resolve_active_provider(db, company_id=cid)
    assert resolved is None


async def test_free_tier_exhaustion_blocks(session_factory, monkeypatch):
    _set_master_key()
    _managed_on(monkeypatch, free=100, daily=0)  # daily guard off
    cid, uid = await _make_company(session_factory)
    from app.services import apikeys, billing

    # Spend up to the free allowance across two charges.
    async with session_factory() as db:
        await billing.record_platform_spend(db, user_id=uid, company_id=cid, cents=60, kind="llm")
        await billing.record_platform_spend(db, user_id=uid, company_id=cid, cents=50, kind="llm")
        await db.commit()

    async with session_factory() as db:
        elig = await billing.eligibility(db, user_id=uid)
        assert elig.allowed is False
        resolved = await apikeys.resolve_active_provider(db, company_id=cid)
    assert resolved is None


async def test_record_platform_spend_writes_ledger_and_total(session_factory, monkeypatch):
    _set_master_key()
    _managed_on(monkeypatch)
    cid, uid = await _make_company(session_factory)
    from sqlalchemy import func, select

    from app.models import PlatformBillingAccount, PlatformCharge
    from app.services import billing

    async with session_factory() as db:
        await billing.record_platform_spend(db, user_id=uid, company_id=cid, cents=25, kind="llm")
        await billing.record_platform_spend(db, user_id=uid, company_id=cid, cents=15, kind="web_search")
        await db.commit()

    async with session_factory() as db:
        account = await db.scalar(
            select(PlatformBillingAccount).where(PlatformBillingAccount.user_id == uid)
        )
        assert account is not None
        assert account.platform_spent_cents == 40
        rows = await db.scalar(
            select(func.count()).select_from(PlatformCharge).where(PlatformCharge.user_id == uid)
        )
        assert rows == 2


async def test_daily_cap_blocks_even_within_free_allowance(session_factory, monkeypatch):
    _set_master_key()
    _managed_on(monkeypatch, free=10_000, daily=50)
    cid, uid = await _make_company(session_factory)
    from app.services import billing

    async with session_factory() as db:
        await billing.record_platform_spend(db, user_id=uid, company_id=cid, cents=60, kind="llm")
        await db.commit()

    async with session_factory() as db:
        elig = await billing.eligibility(db, user_id=uid)
        # Free allowance is nowhere near exhausted, but the daily burst cap is hit.
        assert elig.allowed is False


async def test_paid_managed_allowed_beyond_free_allowance(session_factory, monkeypatch):
    _set_master_key()
    _managed_on(monkeypatch, free=100, daily=0)
    cid, uid = await _make_company(session_factory)
    from app.services import apikeys, billing

    async with session_factory() as db:
        await billing.record_platform_spend(db, user_id=uid, company_id=cid, cents=500, kind="llm")
        await billing.mark_paid_managed(db, user_id=uid)
        await db.commit()

    async with session_factory() as db:
        elig = await billing.eligibility(db, user_id=uid)
        assert elig.allowed is True
        resolved = await apikeys.resolve_active_provider(db, company_id=cid)
    assert resolved is not None
    assert resolved.source == "platform"
