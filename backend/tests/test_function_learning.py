"""Cross-company function learning (RFC 0002, slice 4): aggregate per-function
performance across companies and prioritize the laggards' playbooks for the
skill-optimizer, so a fix propagates to everyone running that function.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models import Company, MetricSignal
from app.models.enums import MetricSource
from app.runtime.skill_optimizer import merge_priority_candidates
from app.services import function_catalog as fc
from app.services import function_learning as fl
from app.services.onboarding import provision_fleet
from app.services.skill_signal import SkillSignal
from tests.conftest import requires_db


def test_trend_is_direction_aware():
    assert fl.trend([(1, 10.0), (2, 20.0)], lower_is_better=False) == "improved"
    assert fl.trend([(1, 20.0), (2, 10.0)], lower_is_better=True) == "improved"
    assert fl.trend([(1, 10.0), (2, 5.0)], lower_is_better=False) == "declined"
    assert fl.trend([(1, 5.0), (2, 5.0)], lower_is_better=False) == "flat"
    assert fl.trend([(1, 5.0)], lower_is_better=False) == "insufficient"


def _perf(**kw):
    base = dict(function="website", title="Web", default_skills=("seo-keyword-strategy",),
                adoption=0, measuring=0, improved=0, declined=0)
    return fl.FunctionPerformance(**{**base, **kw})


def test_priority_skills_flags_undermeasured_and_declining():
    under = _perf(adoption=4, measuring=1)  # <half measuring → lagging
    assert under.lagging
    declining = _perf(adoption=2, measuring=2, improved=0, declined=3)
    assert declining.lagging
    healthy = _perf(adoption=3, measuring=3, improved=4, declined=0)
    assert not healthy.lagging

    skills = fl.priority_skills([under, healthy], min_adoption=2)
    assert "seo-keyword-strategy" in skills
    assert "companies" in skills["seo-keyword-strategy"]
    # A healthy function contributes nothing to optimize.
    assert fl.priority_skills([healthy], min_adoption=2) == {}


def test_merge_priority_candidates_leads_with_business_signal():
    ranked = [SkillSignal(skill_name="a", sample_count=5, success_count=2, failure_count=3)]
    merged = merge_priority_candidates(
        ranked, {"b": "cross-co reason", "a": "also lagging"}, batch=5
    )
    names = [s.skill_name for s in merged]
    assert names[:2] == ["b", "a"]  # priority skills lead
    a = next(s for s in merged if s.skill_name == "a")
    assert a.context == "also lagging" and a.sample_count == 5  # task signal kept + context
    b = next(s for s in merged if s.skill_name == "b")
    assert b.sample_count == 0 and b.context == "cross-co reason"  # synthetic
    # Batch cap is honored.
    assert len(merge_priority_candidates(ranked, {"b": "x", "c": "y"}, batch=1)) == 1


def test_winners_and_reinforcement_note():
    winning = _perf(function="outbound", title="Outbound", adoption=3, measuring=3,
                    improved=5, declined=1)
    lagging = _perf(function="website", title="Web", adoption=3, measuring=1)
    one_off = _perf(function="social", title="Social", adoption=1, measuring=1, improved=2)
    perfs = [winning, lagging, one_off]
    keys = fl.winning_functions(perfs, min_adoption=2)
    assert keys == {"outbound"}  # min_adoption filters the single-company one
    assert "proven winner" in fl.reinforcement_note("outbound", perfs)
    assert fl.reinforcement_note("website", perfs) == ""  # lagging, not a winner


@requires_db
async def test_aggregate_reads_signals_across_companies(session_factory, company_with_budget):
    # Two companies both staff `website`; one has a declining KPI, the other measures
    # nothing — so `website` should read as lagging across the platform.
    async with session_factory() as db:
        c1 = await db.get(Company, company_with_budget)
        await provision_fleet(db, company=c1, specs=fc.resolve_selection(["website"]),
                              total_budget_cents=10_000)
        c2 = Company(owner_user_id=c1.owner_user_id, name="C2")
        db.add(c2)
        await db.flush()
        await provision_fleet(db, company=c2, specs=fc.resolve_selection(["website"]),
                              total_budget_cents=10_000)
        now = datetime.now(UTC)
        # c1: signup_conversion_rate falls (higher-is-better → declined).
        db.add_all([
            MetricSignal(company_id=c1.id, name="signup_conversion_rate", value=0.3,
                         source=MetricSource.founder, captured_at=now - timedelta(days=2)),
            MetricSignal(company_id=c1.id, name="signup_conversion_rate", value=0.1,
                         source=MetricSource.founder, captured_at=now),
        ])
        await db.commit()

    async with session_factory() as db:  # tenant-unset → cross-company
        perfs = await fl.aggregate(db)

    web = next(p for p in perfs if p.function == "website")
    assert web.adoption == 2
    assert web.measuring == 1  # only c1 has data
    assert web.declined == 1 and web.improved == 0
    assert web.lagging
    assert "seo-keyword-strategy" in fl.priority_skills(perfs, min_adoption=2)
