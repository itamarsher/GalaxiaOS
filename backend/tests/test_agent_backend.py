"""Founder-only agent runtime switch: native ⇄ external (RFC 0001)."""

from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.db import get_db
from app.models import Agent, Company, Membership, User
from app.models.enums import AgentBackendType, AgentRole, CompanyStatus, MembershipRole
from app.security import create_access_token
from tests.conftest import requires_db


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


def _auth(uid):
    return {"Authorization": f"Bearer {create_access_token(uid)}"}


async def _seed(session_factory):
    async with session_factory() as db:
        founder = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        other = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add_all([founder, other])
        await db.flush()
        company = Company(owner_user_id=founder.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=founder.id, company_id=company.id, role=MembershipRole.founder))
        db.add(Membership(user_id=other.id, company_id=company.id, role=MembershipRole.admin))
        ceo = Agent(company_id=company.id, role=AgentRole.ceo, name="CEO")
        growth = Agent(company_id=company.id, role=AgentRole.growth, name="Growth")
        db.add_all([ceo, growth])
        await db.flush()
        await db.commit()
        return company.id, founder.id, other.id, ceo.id, growth.id


@requires_db
async def test_founder_can_switch_agent_to_external_and_back(session_factory):
    company_id, founder_id, other_id, ceo_id, growth_id = await _seed(session_factory)
    with _client() as client:
        base = f"/companies/{company_id}/agents"

        # Founder flips the growth agent to the external (connected) runtime.
        r = client.put(f"{base}/{growth_id}/backend", headers=_auth(founder_id),
                       json={"backend_type": "external"})
        assert r.status_code == 200 and r.json()["backend_type"] == "external"

        # …a human can also staff the function (RFC 0001 step 6)…
        r = client.put(f"{base}/{growth_id}/backend", headers=_auth(founder_id),
                       json={"backend_type": "human"})
        assert r.status_code == 200 and r.json()["backend_type"] == "human"

        # …and back to native.
        r = client.put(f"{base}/{growth_id}/backend", headers=_auth(founder_id),
                       json={"backend_type": "native"})
        assert r.status_code == 200 and r.json()["backend_type"] == "native"

        # A non-founder can't.
        assert client.put(f"{base}/{growth_id}/backend", headers=_auth(other_id),
                          json={"backend_type": "external"}).status_code == 403

        # The CEO must stay native (it orchestrates the company) — no external, no human.
        assert client.put(f"{base}/{ceo_id}/backend", headers=_auth(founder_id),
                          json={"backend_type": "external"}).status_code == 400
        assert client.put(f"{base}/{ceo_id}/backend", headers=_auth(founder_id),
                          json={"backend_type": "human"}).status_code == 400

        # Invalid / non-settable values are rejected.
        assert client.put(f"{base}/{growth_id}/backend", headers=_auth(founder_id),
                          json={"backend_type": "marketplace"}).status_code == 400
        assert client.put(f"{base}/{growth_id}/backend", headers=_auth(founder_id),
                          json={"backend_type": "bogus"}).status_code == 400

    async with session_factory() as db:
        assert (await db.get(Agent, growth_id)).backend_type is AgentBackendType.native
