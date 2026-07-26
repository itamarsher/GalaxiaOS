"""Auto-capture health signals from connected data (RFC 0002): derive KPIs from the
CRM and runway the company already has, and let the founder retarget a KR over MCP.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Company, CrmContact, CrmDeal, MetricSignal, Mission, RunwaySnapshot
from app.models.enums import CrmContactStatus, CrmDealStage
from app.services import function_catalog as fc
from app.services import function_health as fh
from app.services import signal_capture
from app.services.onboarding import provision_fleet
from tests.conftest import requires_db


@requires_db
async def test_capture_derives_crm_and_runway_signals(session_factory, company_with_budget):
    async with session_factory() as db:
        cid = company_with_budget
        db.add_all([
            CrmContact(company_id=cid, name="A", status=CrmContactStatus.lead),
            CrmContact(company_id=cid, name="B", status=CrmContactStatus.lead),
            CrmContact(company_id=cid, name="C", status=CrmContactStatus.customer),  # not a lead
            CrmDeal(company_id=cid, title="D1", stage=CrmDealStage.proposal, amount_cents=500_00),
            CrmDeal(company_id=cid, title="D2", stage=CrmDealStage.won, amount_cents=999_00),  # terminal
            RunwaySnapshot(company_id=cid, balance_cents=600_00,
                           burn_rate_cents_per_day=1000, projected_days_remaining=60.0),
        ])
        await db.commit()

    async with session_factory() as db:
        recorded = await signal_capture.capture(db, company_id=company_with_budget)
        await db.commit()

    assert recorded["inbound_leads"] == 2.0            # only the two leads
    assert recorded["pipeline_created"] == 500.0        # open deal only, in USD
    assert recorded["runway_months"] == 2.0             # 60 days / 30
    assert recorded["burn_rate"] == 300.0               # 1000c/day * 30 / 100

    # A second capture with no change records nothing new (series stays bounded).
    async with session_factory() as db:
        again = await signal_capture.capture(db, company_id=company_with_budget)
        await db.commit()
    assert again == {}

    async with session_factory() as db:
        n = await db.scalar(select(func.count()).select_from(MetricSignal).where(
            MetricSignal.company_id == company_with_budget,
            MetricSignal.name == "inbound_leads"))
        assert n == 1  # not duplicated


@requires_db
async def test_set_target_edits_and_clears_a_kr(session_factory, company_with_budget):
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        db.add(Mission(company_id=company.id, raw_text="m"))
        await db.flush()
        await provision_fleet(db, company=company,
                              specs=fc.resolve_selection(["website"]), total_budget_cents=10_000)
        await fh.sync_health_krs(db, company=company)
        await db.commit()

    async with session_factory() as db:
        result = await fh.set_target(db, company_id=company_with_budget,
                                     metric="signup_conversion_rate", target=0.09)
        await db.commit()
    assert result["target"] == 0.09

    async with session_factory() as db:
        targets = await fh.kr_targets(db, company_id=company_with_budget)
        assert targets["signup_conversion_rate"] == 0.09

    # Clearing sets it back to no target (drops out of kr_targets).
    async with session_factory() as db:
        await fh.set_target(db, company_id=company_with_budget,
                            metric="signup_conversion_rate", target=None)
        await db.commit()
    async with session_factory() as db:
        assert "signup_conversion_rate" not in await fh.kr_targets(db, company_id=company_with_budget)

    # An unknown KPI is a clean error, not a crash.
    async with session_factory() as db:
        with pytest.raises(ValueError):
            await fh.set_target(db, company_id=company_with_budget, metric="nope", target=1)
