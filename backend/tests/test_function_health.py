"""Formal health KRs + agent-based metrics (RFC 0002): seed KRs from a function's
health signals (business + agent-based), record agent KPIs from reputation, and
drive off-target detection in the improvement cycle.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, Company, KeyResult, Mission, Objective, ReputationScore
from app.models.enums import AgentRole
from app.services import function_catalog as fc
from app.services import function_health as fh
from app.services import function_improvement as fi
from app.services import function_metrics as fm
from app.services import metrics
from app.services.onboarding import provision_fleet
from tests.conftest import requires_db


def test_signal_metadata_covers_catalog_and_agent_kpis():
    # Every catalog health signal has metadata (unit + direction + optional target).
    for f in fc.selectable_functions():
        for s in f.health_signals:
            assert s in fm.SIGNAL_META, f"{s} missing metadata"
    assert fm.is_lower_better("bounce_rate") and not fm.is_lower_better("signup_conversion_rate")
    assert fm.default_target("signup_conversion_rate") == 0.05
    assert set(fm.AGENT_SIGNALS) <= set(fm.SIGNAL_META)


async def _kr_metrics(db, company_id):
    rows = await db.execute(
        select(KeyResult.metric)
        .join(Objective, Objective.id == KeyResult.objective_id)
        .where(Objective.title == fh.HEALTH_OBJECTIVE_TITLE,
               KeyResult.company_id == company_id)
    )
    return {m for (m,) in rows}


@requires_db
async def test_sync_seeds_business_and_agent_krs_and_prunes(session_factory, company_with_budget):
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        db.add(Mission(company_id=company.id, raw_text="test mission"))
        await db.flush()
        await provision_fleet(db, company=company,
                              specs=fc.resolve_selection(["website"]), total_budget_cents=10_000)
        await fh.sync_health_krs(db, company=company)
        await db.commit()

    async with session_factory() as db:
        metrics_set = await _kr_metrics(db, company_with_budget)
        # Business KPIs for website…
        assert {"signup_conversion_rate", "bounce_rate", "website_visitors"} <= metrics_set
        # …plus the agent-based KPIs (some KRs are agent-based, as required).
        assert {"agent_reliability", "agent_trust", "agent_roi"} <= metrics_set
        # A seeded KR carries its unit + default target.
        conv = await db.scalar(select(KeyResult).where(
            KeyResult.company_id == company_with_budget,
            KeyResult.metric == "signup_conversion_rate"))
        assert conv.target_value == 0.05 and conv.unit == "ratio"

    # Drop the website function; its business KRs are pruned, agent KRs remain.
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        web = await db.scalar(select(Agent).where(
            Agent.company_id == company_with_budget, Agent.role == AgentRole.custom))
        await db.delete(web)
        await db.flush()
        await fh.sync_health_krs(db, company=company)
        await db.commit()

    async with session_factory() as db:
        metrics_set = await _kr_metrics(db, company_with_budget)
        assert "signup_conversion_rate" not in metrics_set  # pruned
        assert "agent_reliability" in metrics_set  # company-level, kept


@requires_db
async def test_record_agent_signals_from_reputation(session_factory, company_with_budget):
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        db.add(Mission(company_id=company.id, raw_text="test mission"))
        await db.flush()
        await provision_fleet(db, company=company,
                              specs=fc.resolve_selection(["website"]), total_budget_cents=10_000)
        await fh.sync_health_krs(db, company=company)
        ceo = await db.scalar(select(Agent).where(
            Agent.company_id == company_with_budget, Agent.role == AgentRole.ceo))
        db.add(ReputationScore(company_id=company_with_budget, agent_id=ceo.id,
                               reliability=0.9, trust=0.8, roi=0.6, sample_count=4))
        await db.commit()

    async with session_factory() as db:
        assert await fh.record_agent_signals(db, company_id=company_with_budget) is True
        await fh.refresh_kr_values(db, company_id=company_with_budget)
        await db.commit()

    async with session_factory() as db:
        rel = await db.scalar(select(KeyResult).where(
            KeyResult.company_id == company_with_budget, KeyResult.metric == "agent_reliability"))
        assert abs(rel.current_value - 0.9) < 1e-6  # refreshed from the recorded signal


@requires_db
async def test_off_target_drives_the_improvement_cycle(session_factory, company_with_budget):
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        db.add(Mission(company_id=company.id, raw_text="test mission"))
        await db.flush()
        await provision_fleet(db, company=company,
                              specs=fc.resolve_selection(["website"]), total_budget_cents=10_000)
        await fh.sync_health_krs(db, company=company)
        # Measured, but below the seeded 0.05 target.
        await metrics.record_signal(db, company_id=company_with_budget,
                                    name="signup_conversion_rate", value=0.02)
        await fh.refresh_kr_values(db, company_id=company_with_budget)
        await db.commit()

    async with session_factory() as db:
        statuses = await fi.assess_functions(db, company_id=company_with_budget)
    web = next(s for s in statuses if s.function == "website")
    assert "signup_conversion_rate" in web.off_target
    assert not web.on_track
    assert "below target" in fi.improvement_brief(statuses)
