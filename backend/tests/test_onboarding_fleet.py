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


def test_split_budget_sums_to_total_and_is_even():
    parts = onboarding._split_budget(50_000, 6)
    assert sum(parts) == 50_000
    assert max(parts) - min(parts) <= 1
    assert onboarding._split_budget(0, 3) == [None, None, None]
    assert onboarding._split_budget(100, 0) == []


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
        allocated = [a.monthly_budget_cents for a in agents]
        assert len(agents) == 4
        assert all(c is not None for c in allocated)
        assert sum(allocated) == 10_000  # the whole budget is distributed
