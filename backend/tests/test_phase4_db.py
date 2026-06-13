"""DB-backed Phase 4 tests (non-vector): runway, reputation, low-ROI pause."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models import Agent, Budget, DecisionRequest, ReputationScore, SpendEntry
from app.models.enums import AgentRole, AgentStatus, DecisionKind, SpendCategory
from app.services import reputation
from app.services import runway as runway_svc
from tests.conftest import requires_db


@requires_db
async def test_runway_recompute_and_low_runway_alert(session_factory, company_with_budget):
    company_id = company_with_budget  # limit 10_000c
    async with session_factory() as db:
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
        # Spend 9000c this week -> burn ~1285c/day, balance 1000c -> < 1 day runway.
        db.add(
            SpendEntry(
                company_id=company_id,
                budget_id=budget.id,
                category=SpendCategory.llm,
                amount_cents=9000,
            )
        )
        budget.spent_cents = 9000
        await db.commit()

    async with session_factory() as db:
        snap = await runway_svc.recompute(db, company_id)
        await db.commit()
        assert snap.burn_rate_cents_per_day > 0
        assert snap.projected_days_remaining is not None
        assert snap.projected_days_remaining < 14

        alert = await db.scalar(
            select(DecisionRequest).where(
                DecisionRequest.company_id == company_id,
                DecisionRequest.kind == DecisionKind.strategy,
            )
        )
        assert alert is not None
        assert "Runway low" in alert.summary


@requires_db
async def test_reputation_records_and_updates(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add(agent)
        await db.flush()
        agent_id = agent.id

        await reputation.record_task_outcome(
            db, company_id=company_id, agent_id=agent_id, success=True, cost_cents=100
        )
        await reputation.record_task_outcome(
            db, company_id=company_id, agent_id=agent_id, success=False, cost_cents=0
        )
        await db.commit()

        score = await db.scalar(
            select(ReputationScore).where(ReputationScore.agent_id == agent_id)
        )
        assert score.sample_count == 2
        assert 0.0 < score.reliability < 1.0  # one success, one failure
        assert 0.0 <= score.trust <= 1.0


@requires_db
async def test_pause_low_roi_agents(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        good = Agent(company_id=company_id, role=AgentRole.research, name="Research")
        bad = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add_all([good, bad])
        await db.flush()
        db.add_all(
            [
                ReputationScore(company_id=company_id, agent_id=good.id, roi=0.8, sample_count=3),
                ReputationScore(company_id=company_id, agent_id=bad.id, roi=0.01, sample_count=3),
            ]
        )
        await db.commit()

        paused = await runway_svc.pause_low_roi_agents(db, company_id, roi_threshold=0.05)
        await db.commit()
        assert paused == [bad.id]

        refreshed_bad = await db.get(Agent, bad.id)
        refreshed_good = await db.get(Agent, good.id)
        assert refreshed_bad.status is AgentStatus.paused
        assert refreshed_good.status is AgentStatus.active
