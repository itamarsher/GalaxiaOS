"""Galaxia reset: rebuild from fleet creation while preserving saved BYOK keys.

The heavily-developed dogfooding company needs a clean-slate restart that does NOT
force re-entering the model key. These tests prove reset wipes generated state,
rebuilds the fleet, and keeps stored provider keys usable — and that ordinary
boots reconcile the mission text to config.
"""

from __future__ import annotations

import base64
import os

from sqlalchemy import select

from app.config import settings
from app.models import Agent, ApiKey, Company, Mission
from app.models.enums import AgentRole, ApiKeyStatus
from app.services import apikeys, galaxia
from tests.conftest import requires_db


def _set_master_key() -> None:
    settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


@requires_db
async def test_reset_rebuilds_fleet_and_preserves_keys(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await galaxia._run(db)
        await apikeys.store_key(
            db, company_id=cid, provider="anthropic", plaintext="sk-secret-123"
        )
        # A stray agent proves the reset actually wipes generated state.
        db.add(Agent(company_id=cid, role=AgentRole.custom, name="STRAY"))
        await db.commit()

    async with session_factory() as db:
        cid2 = await galaxia.reset_galaxia(db)
        await db.commit()
    assert cid2 == cid

    async with session_factory() as db:
        # Company survives (same id); fleet rebuilt fresh; stray gone.
        assert await db.get(Company, cid) is not None
        agents = (await db.scalars(select(Agent).where(Agent.company_id == cid))).all()
        assert "STRAY" not in {a.name for a in agents}
        assert AgentRole.platform in {a.role for a in agents}
        assert AgentRole.ceo in {a.role for a in agents}

        # Mission set from config.
        mission = await db.scalar(select(Mission).where(Mission.company_id == cid))
        assert mission is not None and mission.raw_text == settings.galaxia_mission

        # The point: the saved key survived the delete + re-provision and still decrypts.
        pt = await apikeys.get_plaintext_key(db, company_id=cid, provider="anthropic")
        assert pt == "sk-secret-123"
        active = (
            await db.scalars(
                select(ApiKey).where(
                    ApiKey.company_id == cid, ApiKey.status == ApiKeyStatus.active
                )
            )
        ).all()
        assert len(active) == 1  # exactly one, not duplicated


@requires_db
async def test_boot_reconciles_mission_to_config(session_factory, monkeypatch):
    async with session_factory() as db:
        cid = await galaxia._run(db)
        await db.commit()

    monkeypatch.setattr(settings, "galaxia_mission", "A NEW MISSION FROM CONFIG")
    monkeypatch.setattr(settings, "galaxia_constraints", ["only this constraint"])
    async with session_factory() as db:
        # Company exists → the boot path reconciles the mission instead of re-provisioning.
        await galaxia._run(db)
        await db.commit()

    async with session_factory() as db:
        mission = await db.scalar(select(Mission).where(Mission.company_id == cid))
        assert mission.raw_text == "A NEW MISSION FROM CONFIG"
        assert mission.constraints == ["only this constraint"]
        # Fleet was not duplicated by the reconcile (one agent per role).
        roles = [
            a.role for a in (await db.scalars(select(Agent).where(Agent.company_id == cid))).all()
        ]
        assert len(roles) == len(set(roles))
