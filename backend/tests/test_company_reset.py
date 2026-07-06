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
