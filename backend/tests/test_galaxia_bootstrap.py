"""Galaxia bootstrap: the dogfooding company that drives the demand→issue loop.

P0-1 of the dogfooding gap analysis (docs/GALAXIA_DOGFOODING.md): the promoter
tools are keyed to a fixed founder-user membership, so that company must actually
exist. These tests prove the bootstrap provisions it deterministically, is
idempotent (safe to run on every boot / from concurrent processes), and — the
point of the whole thing — that it authorizes the Platform promoter gate.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.config import settings
from app.models import Agent, Budget, Company, Membership, Mission, Policy
from app.models.enums import AgentRole, CompanyStatus
from app.runtime.tools.platform import _is_abos_admin_company
from app.services import galaxia
from tests.conftest import requires_db


@requires_db
async def test_bootstrap_provisions_company_and_authorizes_promoter(session_factory):
    async with session_factory() as db:
        company_id = await galaxia._bootstrap(db)
        await db.commit()

    assert company_id == galaxia.galaxia_company_id()

    async with session_factory() as db:
        company = await db.get(Company, company_id)
        assert company is not None
        assert company.name == settings.galaxia_company_name
        assert company.status is CompanyStatus.active  # active → cron picks it up
        assert company.mission_id is not None

        # Founder membership under the FIXED promoter-gate id (not just any user).
        membership = await db.scalar(
            select(Membership).where(
                Membership.company_id == company_id,
                Membership.user_id == galaxia.galaxia_founder_user_id(),
            )
        )
        assert membership is not None

        # Mission + budget seeded.
        mission = await db.scalar(select(Mission).where(Mission.company_id == company_id))
        assert mission is not None and mission.raw_text == settings.galaxia_mission
        budget = await db.scalar(select(Budget).where(Budget.company_id == company_id))
        assert budget is not None
        assert budget.limit_cents == settings.galaxia_monthly_budget_cents

        # Fleet includes the guaranteed Platform agent (the promoter) and a CEO.
        roles = [
            a.role
            for a in (
                await db.scalars(select(Agent).where(Agent.company_id == company_id))
            ).all()
        ]
        assert AgentRole.platform in roles
        assert AgentRole.ceo in roles

        # Governance seeded (default spend policies exist).
        policies = (
            await db.scalars(select(Policy).where(Policy.company_id == company_id))
        ).all()
        assert len(policies) >= 1

        # The payoff: the Platform promoter gate now authorizes Galaxia.
        assert await _is_abos_admin_company(db, company_id) is True


@requires_db
async def test_bootstrap_is_idempotent(session_factory):
    """Running it twice yields one company and one fleet — no duplicate rows."""
    async with session_factory() as db:
        cid1 = await galaxia._bootstrap(db)
        await db.commit()
    async with session_factory() as db:
        cid2 = await galaxia._bootstrap(db)
        await db.commit()

    assert cid1 == cid2

    async with session_factory() as db:
        companies = (
            await db.scalars(select(Company).where(Company.id == cid1))
        ).all()
        assert len(companies) == 1

        agents = (
            await db.scalars(select(Agent).where(Agent.company_id == cid1))
        ).all()
        agent_roles = [a.role for a in agents]
        # Idempotent: the second run created no second fleet (one agent per role).
        assert len(agent_roles) == len(set(agent_roles))

        memberships = (
            await db.scalars(select(Membership).where(Membership.company_id == cid1))
        ).all()
        assert len(memberships) == 1


@requires_db
async def test_other_company_is_not_authorized_as_promoter(
    session_factory, company_with_budget
):
    """A normal tenant's Platform agent must NOT pass the promoter gate."""
    async with session_factory() as db:
        assert await _is_abos_admin_company(db, company_with_budget) is False


@pytest.mark.asyncio
async def test_bootstrap_disabled_returns_none(monkeypatch):
    """The kill-switch short-circuits before touching the database."""
    monkeypatch.setattr(settings, "galaxia_bootstrap_enabled", False)
    assert await galaxia.ensure_bootstrap() is None
