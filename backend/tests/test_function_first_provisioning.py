"""Function-first provisioning (RFC 0002, slice 2): a founder's picked functions
spin up as real agents that carry their function identity, health target, and
skills — the seam `onboarding.generate` uses on the function-first path.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, Company
from app.models.enums import AgentRole
from app.services import function_catalog as fc
from app.services.onboarding import provision_fleet
from tests.conftest import requires_db


@requires_db
async def test_selected_functions_provision_with_config_and_health_target(
    session_factory, company_with_budget
):
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        # Founder picks an in-house block and the external one.
        await provision_fleet(
            db, company=company,
            specs=fc.resolve_selection(["website", "billing"]),
            total_budget_cents=10_000,
        )
        await db.commit()

    async with session_factory() as db:
        agents = (
            await db.scalars(select(Agent).where(Agent.company_id == company_with_budget))
        ).all()

    by_fn = {(a.config or {}).get("function"): a for a in agents}
    # The picks are provisioned and carry their function identity in config…
    assert "website" in by_fn and "billing" in by_fn
    # …the in-house block's health target is baked into its prompt…
    assert "signup_conversion_rate" in by_fn["website"].system_prompt
    assert "signup_conversion_rate" in by_fn["website"].config["health_signals"]
    assert by_fn["website"].config["implementation"] == "in_house"
    # …and the external block is marked so the connect-prompt can find it.
    assert by_fn["billing"].config["implementation"] == "external"
    assert "external provider" in by_fn["billing"].system_prompt
    # Oversight is guaranteed regardless of what was picked.
    roles = {a.role for a in agents}
    assert {AgentRole.ceo, AgentRole.governance, AgentRole.auditor,
            AgentRole.data, AgentRole.platform} <= roles
