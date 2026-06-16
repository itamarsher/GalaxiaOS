"""Onboarding fleet generation + budget allocation.

Covers the bug where the org-design LLM returned an empty ``agents`` list and the
company was left with no fleet, plus the budget-reallocation behavior.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, Budget
from app.models.enums import AgentRole
from app.services import onboarding
from tests.conftest import requires_db


def test_fleet_specs_backfills_empty_llm_output():
    # Nothing usable from the model -> full default fleet.
    roles = [s["role"] for s in onboarding._fleet_specs([])]
    assert roles[0] == "ceo"
    assert "governance" in roles
    assert len(roles) >= 4


def test_fleet_specs_guarantees_ceo_and_governance():
    roles = [s["role"] for s in onboarding._fleet_specs([{"role": "growth", "name": "G"}])]
    assert "ceo" in roles
    assert "growth" in roles
    assert "governance" in roles


def test_weighted_split_sums_to_total_and_weights_ceo_lower():
    # ceo, growth, research, governance weights: 1, 3, 2, 1
    weights = [1.0, 3.0, 2.0, 1.0]
    parts = onboarding._weighted_split(weights, 70_000)
    assert sum(parts) == 70_000  # no cents lost to rounding
    # Growth (weight 3) gets the most; CEO/Governance (weight 1) the least.
    assert parts[1] == max(parts)
    assert parts[0] < parts[1]
    assert parts[0] <= parts[2]
    assert onboarding._weighted_split([1.0, 1.0, 1.0], 0) == [None, None, None]
    assert onboarding._weighted_split([], 100) == []


@requires_db
async def test_reallocate_agent_budgets(session_factory, company_with_budget):
    company_id = company_with_budget  # limit 10_000c
    async with session_factory() as db:
        for role in (AgentRole.ceo, AgentRole.growth, AgentRole.finance, AgentRole.governance):
            db.add(Agent(company_id=company_id, role=role, name=role.value))
        await db.commit()

    async with session_factory() as db:
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
        await onboarding._reallocate_agent_budgets(
            db, company_id=company_id, total_cents=budget.limit_cents
        )
        await db.commit()

    async with session_factory() as db:
        agents = (await db.scalars(select(Agent).where(Agent.company_id == company_id))).all()
        by_role = {a.role: a.monthly_budget_cents for a in agents}
        assert len(agents) == 4
        assert all(c is not None for c in by_role.values())
        assert sum(by_role.values()) == 10_000  # the whole budget is distributed
        # Weighted: growth (3) > finance (1.5) > ceo ~= governance (both 1;
        # may differ by a single leftover cent from largest-remainder rounding).
        assert by_role[AgentRole.growth] > by_role[AgentRole.finance]
        assert by_role[AgentRole.finance] > by_role[AgentRole.ceo]
        assert abs(by_role[AgentRole.ceo] - by_role[AgentRole.governance]) <= 1
