"""Tests for the data-segmentation policy (RFC 0001).

Covers the enforcement primitive (founder + CEO bypass; deny-if-any-label-missing),
the seeded taxonomy, and the founder-controlled management endpoints.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.db import get_db
from app.models import Agent, Company, Membership, User
from app.models.enums import AgentRole, CompanyStatus, MembershipRole
from app.security import create_access_token
from app.services import data_policy
from tests.conftest import requires_db


# ── pure enforcement primitive (no DB) ─────────────────────────────────────────
def test_permits_is_subset_and_unlabelled_is_general():
    assert data_policy.permits(["financial"], []) is True  # unlabelled → anyone
    assert data_policy.permits(["financial", "legal"], ["financial"]) is True
    assert data_policy.permits(["financial"], ["financial", "legal"]) is False  # missing legal
    assert data_policy.permits(None, ["financial"]) is False
    assert data_policy.permits(None, None) is True


def test_ceo_and_founder_bypass_segmentation():
    ceo = SimpleNamespace(role=AgentRole.ceo, access_labels=None)
    growth = SimpleNamespace(role=AgentRole.growth, access_labels=["marketing"])
    assert data_policy.agent_can_access(ceo, ["financial", "customers_private"]) is True
    assert data_policy.agent_can_access(growth, ["financial"]) is False
    assert data_policy.agent_can_access(growth, ["marketing"]) is True

    founder = SimpleNamespace(role=MembershipRole.founder, access_labels=None)
    admin = SimpleNamespace(role=MembershipRole.admin, access_labels=["financial"])
    assert data_policy.member_can_access(founder, ["customers_private"]) is True
    assert data_policy.member_can_access(admin, ["customers_private"]) is False
    assert data_policy.member_can_access(admin, ["financial"]) is True


# ── taxonomy + policy over DB ──────────────────────────────────────────────────
@dataclass
class _Ids:
    company_id: uuid.UUID
    founder_id: uuid.UUID
    admin_id: uuid.UUID
    agent_id: uuid.UUID


async def _seed(session_factory) -> _Ids:
    async with session_factory() as db:
        founder = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        admin = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add_all([founder, admin])
        await db.flush()
        company = Company(owner_user_id=founder.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=founder.id, company_id=company.id, role=MembershipRole.founder))
        db.add(Membership(user_id=admin.id, company_id=company.id, role=MembershipRole.admin))
        agent = Agent(company_id=company.id, role=AgentRole.growth, name="Growth Lead")
        db.add(agent)
        await db.flush()
        await db.commit()
        return _Ids(company.id, founder.id, admin.id, agent.id)


@requires_db
async def test_seed_defaults_and_set_access(session_factory):
    ids = await _seed(session_factory)
    async with session_factory() as db:
        labels = await data_policy.list_labels(db, ids.company_id)
        await db.commit()
        keys = {x.key for x in labels}
        assert {"financial", "customers_private", "marketing"} <= keys

    async with session_factory() as db:
        # Founder grants the growth agent only marketing + customers.
        agent = await data_policy.set_agent_access(
            db, ids.company_id, ids.agent_id, ["marketing", "customers"]
        )
        assert agent.access_labels == ["marketing", "customers"]
        # An unknown label is rejected.
        try:
            await data_policy.set_agent_access(db, ids.company_id, ids.agent_id, ["nope"])
            raise AssertionError("expected DataPolicyError")
        except data_policy.DataPolicyError:
            pass


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


@requires_db
async def test_endpoints_are_founder_controlled(session_factory):
    ids = await _seed(session_factory)
    with _client() as client:
        base = f"/companies/{ids.company_id}"

        # Founder lists (seeds defaults), adds a label, assigns agent access.
        r = client.get(f"{base}/data-labels", headers=_auth(ids.founder_id))
        assert r.status_code == 200 and any(x["key"] == "financial" for x in r.json())

        r = client.post(f"{base}/data-labels", headers=_auth(ids.founder_id),
                        json={"key": "board", "name": "Board materials"})
        assert r.status_code == 201

        r = client.put(f"{base}/agents/{ids.agent_id}/access-labels",
                       headers=_auth(ids.founder_id), json={"labels": ["marketing", "board"]})
        assert r.status_code == 200 and set(r.json()["labels"]) == {"marketing", "board"}

        # A non-founder (admin) is forbidden from managing the taxonomy or policy.
        assert client.get(f"{base}/data-labels", headers=_auth(ids.admin_id)).status_code == 403
        assert client.post(f"{base}/data-labels", headers=_auth(ids.admin_id),
                           json={"key": "x", "name": "X"}).status_code == 403
        assert client.put(f"{base}/agents/{ids.agent_id}/access-labels",
                          headers=_auth(ids.admin_id), json={"labels": []}).status_code == 403
