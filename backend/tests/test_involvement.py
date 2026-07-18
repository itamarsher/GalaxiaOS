"""Tests for the human involvement policy (RFC 0001, human binding).

Covers the founder-control invariants: only founder-sanctioned prose becomes the
active involvement the router reads; a teammate can only propose, never
self-escalate; the founder provides or approves.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.db import get_db
from app.models import Company, Membership, User
from app.models.enums import CompanyStatus, MembershipRole
from app.security import create_access_token
from app.services import involvement as involvement_svc
from tests.conftest import requires_db


@dataclass
class _Ids:
    company_id: uuid.UUID
    founder_id: uuid.UUID
    teammate_id: uuid.UUID


async def _seed(session_factory) -> _Ids:
    async with session_factory() as db:
        founder = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        mate = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add_all([founder, mate])
        await db.flush()
        company = Company(owner_user_id=founder.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=founder.id, company_id=company.id, role=MembershipRole.founder))
        db.add(Membership(user_id=mate.id, company_id=company.id, role=MembershipRole.admin))
        await db.commit()
        return _Ids(company.id, founder.id, mate.id)


def _client() -> TestClient:
    async def _override_db():
        engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                yield db
        finally:
            await engine.dispose()

    app = main.create_app()
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _auth(user_id):
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


# ── service-level invariants ───────────────────────────────────────────────────
@requires_db
async def test_propose_does_not_become_active_until_approved(session_factory):
    ids = await _seed(session_factory)
    async with session_factory() as db:
        # Teammate proposes — active involvement stays empty (router reads nothing).
        m = await involvement_svc.propose_involvement(
            db, company_id=ids.company_id, user_id=ids.teammate_id,
            text="I approve anything over $1000",
        )
        assert m.involvement is None and m.proposed_involvement
        await db.commit()

    async with session_factory() as db:
        # Founder approves — the proposal becomes active and the proposal clears.
        m = await involvement_svc.approve_involvement(
            db, company_id=ids.company_id, user_id=ids.teammate_id
        )
        assert m.involvement == "I approve anything over $1000"
        assert m.proposed_involvement is None
        await db.commit()


@requires_db
async def test_founder_can_edit_on_approve_and_set_directly(session_factory):
    ids = await _seed(session_factory)
    async with session_factory() as db:
        await involvement_svc.propose_involvement(
            db, company_id=ids.company_id, user_id=ids.teammate_id, text="approve everything",
        )
        # Founder narrows it on approval — their edit wins.
        m = await involvement_svc.approve_involvement(
            db, company_id=ids.company_id, user_id=ids.teammate_id,
            edited_text="approve only marketing spend",
        )
        assert m.involvement == "approve only marketing spend"
        # Setting directly also clears any later proposal.
        m.proposed_involvement = "sneaky"
        m2 = await involvement_svc.set_involvement(
            db, company_id=ids.company_id, user_id=ids.teammate_id, text="handle support",
        )
        assert m2.involvement == "handle support" and m2.proposed_involvement is None


# ── endpoint-level founder control ─────────────────────────────────────────────
@requires_db
async def test_endpoints_enforce_founder_control(session_factory):
    ids = await _seed(session_factory)
    with _client() as client:
        base = f"/companies/{ids.company_id}"

        # A teammate CANNOT set their own active involvement (no self-escalation)…
        r = client.put(f"{base}/members/{ids.teammate_id}/involvement",
                       json={"text": "I run the whole company"}, headers=_auth(ids.teammate_id))
        assert r.status_code == 403
        # …nor list the team, nor approve.
        assert client.get(f"{base}/involvement", headers=_auth(ids.teammate_id)).status_code == 403

        # A teammate CAN propose their own.
        r = client.put(f"{base}/involvement/proposal",
                       json={"text": "loop me in on hiring"}, headers=_auth(ids.teammate_id))
        assert r.status_code == 200 and r.json()["proposed_involvement"] == "loop me in on hiring"
        assert r.json()["involvement"] is None  # inert until approved

        # The founder approves it → it becomes active.
        r = client.post(f"{base}/members/{ids.teammate_id}/involvement/approve",
                        json={}, headers=_auth(ids.founder_id))
        assert r.status_code == 200 and r.json()["involvement"] == "loop me in on hiring"

        # The founder sets their own involvement directly.
        r = client.put(f"{base}/members/{ids.founder_id}/involvement",
                       json={"text": "approve anything over $500", "coverage": "finance"},
                       headers=_auth(ids.founder_id))
        assert r.status_code == 200 and r.json()["coverage"] == "finance"

        # The founder sees the whole team.
        r = client.get(f"{base}/involvement", headers=_auth(ids.founder_id))
        assert r.status_code == 200 and len(r.json()) == 2
