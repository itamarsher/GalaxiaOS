"""Function-first provisioning (RFC 0002, slice 2): a founder's picked functions
spin up as real agents that carry their function identity, health target, and
skills — the seam `onboarding.generate` uses on the function-first path.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, Budget, Company
from app.models.enums import AgentBackendType, AgentRole, CompanyStatus
from app.services import function_catalog as fc
from app.services import onboarding
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


@requires_db
async def test_engineering_function_provisions_as_external_by_default(
    session_factory, company_with_budget, monkeypatch
):
    """Picking the coding function binds it to the external/pull runtime by default
    (RFC 0003), while a sibling in-house block stays native — no gateway required."""
    from app.config import settings

    monkeypatch.setattr(settings, "delegate_coding_external", True)
    monkeypatch.setattr(settings, "openclaw_base_url", "")  # no push gateway

    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        await provision_fleet(
            db, company=company,
            specs=fc.resolve_selection(["engineering", "website"]),
            total_budget_cents=10_000,
        )
        await db.commit()

    async with session_factory() as db:
        agents = (
            await db.scalars(select(Agent).where(Agent.company_id == company_with_budget))
        ).all()
    by_fn = {(a.config or {}).get("function"): a for a in agents}
    # The coding function is delegated to an external worker…
    assert by_fn["engineering"].backend_type is AgentBackendType.external
    # …while a normal in-house function stays on the native loop…
    assert by_fn["website"].backend_type is AgentBackendType.native
    # …and the CEO always runs natively.
    ceo = next(a for a in agents if a.role is AgentRole.ceo)
    assert ceo.backend_type is AgentBackendType.native


@requires_db
async def test_set_functions_reconciles_add_and_remove(session_factory, company_with_budget):
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        company.status = CompanyStatus.draft  # the picker is draft-only
        await provision_fleet(
            db, company=company, specs=fc.resolve_selection(["website", "social"]),
            total_budget_cents=10_000,
        )
        await db.commit()

    # Reconcile to a different selection: drop social, keep website, add outbound.
    async with session_factory() as db:
        company = await db.get(Company, company_with_budget)
        result = await onboarding.set_functions(
            db, company=company, keys=["website", "outbound"]
        )
        await db.commit()
    assert set(result["functions"]) == {"website", "outbound"}

    async with session_factory() as db:
        selected = set(await onboarding.selected_functions(db, company_id=company_with_budget))
        # Deselected function is gone; oversight (CEO) is untouched.
        assert selected == {"website", "outbound"}
        ceos = (await db.scalars(
            select(Agent).where(Agent.company_id == company_with_budget,
                                Agent.role == AgentRole.ceo)
        )).all()
        assert len(ceos) == 1
        # Budget re-split stays within the company limit.
        budget = await db.scalar(
            select(Budget).where(Budget.company_id == company_with_budget)
        )
        capped = (await db.scalars(
            select(Agent).where(Agent.company_id == company_with_budget,
                                Agent.role != AgentRole.ceo)
        )).all()
        assert sum(a.monthly_budget_cents or 0 for a in capped) <= budget.limit_cents
