"""Generic per-company reset: rebuild a fresh draft, preserve mission + BYOK keys.

The founder-facing analogue of the Galaxia dev reset. These tests prove a reset
wipes the generated org and operational state, rebuilds the default fleet, keeps
the mission text and stored provider keys, and returns the company to draft.
"""

from __future__ import annotations

import base64
import os

from sqlalchemy import select

from app.config import settings
from app.models import Agent, ApiKey, Company, Mission
from app.models.enums import AgentRole, ApiKeyStatus, CompanyStatus
from app.services import apikeys
from app.services.company_reset import reset_company
from tests.conftest import requires_db


def _set_master_key() -> None:
    settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


async def _make_company(db, *, raw_text="Sell great widgets", constraints=("stay lean",)):
    """A minimal active company (user, budget, mission) for reset tests."""
    from app.models import Budget, Membership, User
    from app.models.enums import BudgetPeriod, MembershipRole

    user = User(email=f"founder-{os.urandom(4).hex()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(owner_user_id=user.id, name="Acme", status=CompanyStatus.active)
    db.add(company)
    await db.flush()
    cid = company.id
    db.add(Membership(user_id=user.id, company_id=cid, role=MembershipRole.founder))
    db.add(Budget(company_id=cid, period=BudgetPeriod.monthly, limit_cents=50_000))
    mission = Mission(company_id=cid, raw_text=raw_text, constraints=list(constraints))
    db.add(mission)
    await db.flush()
    company.mission_id = mission.id
    return cid


@requires_db
async def test_reset_company(session_factory):
    _set_master_key()
    async with session_factory() as db:
        # A minimal generic company: user, company (active), budget, mission.
        from app.models import Budget, Membership, User
        from app.models.enums import BudgetPeriod, MembershipRole

        user = User(email="founder@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(
            owner_user_id=user.id, name="Acme", status=CompanyStatus.active
        )
        db.add(company)
        await db.flush()
        cid = company.id
        db.add(Membership(user_id=user.id, company_id=cid, role=MembershipRole.founder))
        db.add(Budget(company_id=cid, period=BudgetPeriod.monthly, limit_cents=50_000))
        mission = Mission(company_id=cid, raw_text="Sell great widgets", constraints=["stay lean"])
        db.add(mission)
        await db.flush()
        company.mission_id = mission.id

        await apikeys.store_key(
            db, company_id=cid, provider="anthropic", plaintext="sk-secret-123"
        )
        # Generated/operational state a reset must clear: a stray custom agent.
        db.add(Agent(company_id=cid, role=AgentRole.custom, name="STRAY"))
        await db.commit()

    async with session_factory() as db:
        company = await db.get(Company, cid)
        fresh = await reset_company(db, company=company)
        await db.commit()
        assert fresh.id == cid

    async with session_factory() as db:
        company = await db.get(Company, cid)
        # Company survives under the same id and is back to draft.
        assert company is not None
        assert company.status is CompanyStatus.draft
        assert company.name == "Acme"

        # Generated + operational state wiped; default fleet rebuilt.
        agents = (await db.scalars(select(Agent).where(Agent.company_id == cid))).all()
        names = {a.name for a in agents}
        roles = {a.role for a in agents}
        assert "STRAY" not in names
        assert AgentRole.ceo in roles
        assert AgentRole.governance in roles

        # Mission text preserved (not reset to config or blank).
        mission = await db.scalar(select(Mission).where(Mission.company_id == cid))
        assert mission is not None and mission.raw_text == "Sell great widgets"
        assert mission.constraints == ["stay lean"]

        # The saved key survived the delete + re-provision and still decrypts once.
        pt = await apikeys.get_plaintext_key(db, company_id=cid, provider="anthropic")
        assert pt == "sk-secret-123"
        active = (
            await db.scalars(
                select(ApiKey).where(
                    ApiKey.company_id == cid, ApiKey.status == ApiKeyStatus.active
                )
            )
        ).all()
        assert len(active) == 1


@requires_db
async def test_reset_preserves_member_involvement_and_access(session_factory):
    """A reset must keep each member's involvement + access config, not just (user, role).

    Regression: reset rebuilt memberships as ``Membership(user, company, role)`` and
    dropped ``involvement`` — silently disarming the founder's approval gates (the
    involvement router auto-approves when no one has opted into a decision kind).
    """
    from app.models import Membership
    from app.models.enums import MembershipRole

    async with session_factory() as db:
        cid = await _make_company(db)
        m = await db.scalar(select(Membership).where(Membership.company_id == cid))
        m.involvement = "Approve every plan, hire, spend, and outbound comm before it proceeds."
        m.proposed_involvement = "pending change"
        m.access_labels = ["financial", "legal"]
        m.coverage = "weekdays 9-5"
        await db.commit()

    async with session_factory() as db:
        company = await db.get(Company, cid)
        await reset_company(db, company=company)
        await db.commit()

    async with session_factory() as db:
        m = await db.scalar(select(Membership).where(Membership.company_id == cid))
        assert m is not None and m.role is MembershipRole.founder
        # The gate-driving fields survive the cascade-delete + rebuild.
        assert m.involvement == "Approve every plan, hire, spend, and outbound comm before it proceeds."
        assert m.proposed_involvement == "pending change"
        assert m.access_labels == ["financial", "legal"]
        assert m.coverage == "weekdays 9-5"


@requires_db
async def test_reset_company_with_edited_mission(session_factory):
    """A founder can revise the mission as part of the reset (relaunch)."""
    _set_master_key()
    async with session_factory() as db:
        cid = await _make_company(db, raw_text="Sell great widgets", constraints=("stay lean",))
        # A previously detected language must not stick to the new mission text.
        mission = await db.scalar(select(Mission).where(Mission.company_id == cid))
        mission.language = "en"
        await db.commit()

    async with session_factory() as db:
        company = await db.get(Company, cid)
        await reset_company(
            db,
            company=company,
            mission_text="  Sell premium gadgets in the EU  ",
            constraints=["EU only", "carbon neutral"],
        )
        await db.commit()

    async with session_factory() as db:
        mission = await db.scalar(select(Mission).where(Mission.company_id == cid))
        # Edited text wins (and is stripped); language is re-derived on next generation.
        assert mission.raw_text == "Sell premium gadgets in the EU"
        assert mission.constraints == ["EU only", "carbon neutral"]
        assert mission.language is None


@requires_db
async def test_reset_preserves_mission_when_not_edited(session_factory):
    """Omitting the fields keeps the current mission; ``[]`` explicitly clears constraints."""
    async with session_factory() as db:
        cid = await _make_company(db, raw_text="Original mission", constraints=("keep me",))
        await db.commit()

    # No overrides → mission + constraints preserved verbatim.
    async with session_factory() as db:
        company = await db.get(Company, cid)
        await reset_company(db, company=company)
        await db.commit()
    async with session_factory() as db:
        mission = await db.scalar(select(Mission).where(Mission.company_id == cid))
        assert mission.raw_text == "Original mission"
        assert mission.constraints == ["keep me"]

    # Blank/whitespace mission_text is ignored (treated as "not edited"), but an
    # empty constraints list explicitly clears them.
    async with session_factory() as db:
        company = await db.get(Company, cid)
        await reset_company(db, company=company, mission_text="   ", constraints=[])
        await db.commit()
    async with session_factory() as db:
        mission = await db.scalar(select(Mission).where(Mission.company_id == cid))
        assert mission.raw_text == "Original mission"
        assert mission.constraints == []
