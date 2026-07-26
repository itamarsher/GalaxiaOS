"""The per-function improvement cycle (RFC 0002, slice 3): assess each function
against real metric signals and brief the CEO on what to drive.
"""

from __future__ import annotations

from app.models import Company
from app.services import function_catalog as fc
from app.services import function_improvement as fi
from app.services import metrics
from app.services.onboarding import provision_fleet
from tests.conftest import requires_db


def test_classify_splits_measured_from_unmeasured():
    split = fi.classify(("a", "b", "c"), {"b"})
    assert split["measured"] == ["b"]
    assert split["unmeasured"] == ["a", "c"]
    # No signals recorded → everything is a gap.
    assert fi.classify(("a",), set())["unmeasured"] == ["a"]


def test_classify_flags_off_target_direction_aware():
    split = fi.classify(
        ("signup_conversion_rate", "bounce_rate", "website_visitors"),
        {"signup_conversion_rate", "bounce_rate"},  # measured (visitors not)
        latest_values={"signup_conversion_rate": 0.02, "bounce_rate": 0.6},
        targets={"signup_conversion_rate": 0.05, "bounce_rate": 0.4},
    )
    assert split["unmeasured"] == ["website_visitors"]
    # conversion below target AND bounce_rate above target (lower-is-better) → both off.
    assert set(split["off_target"]) == {"signup_conversion_rate", "bounce_rate"}
    # A measured KPI at/above target is not off.
    ok = fi.classify(("csat",), {"csat"}, latest_values={"csat": 0.95}, targets={"csat": 0.9})
    assert ok["off_target"] == []


def test_brief_is_empty_when_every_function_is_measuring():
    on_track = [fi.FunctionStatus(agent_id=None, function="website", title="Web",
                                  measured=["x"], unmeasured=[])]
    assert fi.improvement_brief(on_track) == ""
    off = [fi.FunctionStatus(agent_id=None, function="outbound", title="Outbound Sales",
                             measured=[], unmeasured=["outbound_reply_rate"])]
    brief = fi.improvement_brief(off)
    assert "Outbound Sales" in brief and "outbound_reply_rate" in brief


@requires_db
async def test_assess_reads_real_signals_per_function(session_factory, company_with_budget):
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        await provision_fleet(
            db, company=company,
            specs=fc.resolve_selection(["website", "billing"]),
            total_budget_cents=10_000,
        )
        # The company has measured one of website's KPIs, nothing for billing.
        await metrics.record_signal(
            db, company_id=company_with_budget, name="signup_conversion_rate", value=0.12
        )
        await db.commit()

    async with session_factory() as db:
        statuses = await fi.assess_functions(db, company_id=company_with_budget)

    by_fn = {s.function: s for s in statuses}
    # Oversight agents are not assessed — only the picked functions.
    assert set(by_fn) == {"website", "billing"}
    assert "signup_conversion_rate" in by_fn["website"].measured
    assert "bounce_rate" in by_fn["website"].unmeasured
    assert by_fn["billing"].measured == []  # nothing recorded → all KPIs are gaps
    assert not by_fn["billing"].on_track

    brief = fi.improvement_brief(statuses)
    assert "Billing & Payments" in brief  # the fully-unmeasured function is driven
