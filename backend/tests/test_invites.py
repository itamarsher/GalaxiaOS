"""Team invites: create/consume/revoke + founder-only endpoints (RFC 0001)."""

from __future__ import annotations

import os
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.db import get_db
from app.models import Company, CompanyInvite, Membership, User
from app.models.enums import CompanyStatus, InviteStatus, MembershipRole
from app.security import create_access_token
from app.services import data_policy
from app.services import invites as invites_svc
from tests.conftest import requires_db


async def _company(session_factory):
    async with session_factory() as db:
        founder = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(founder)
        await db.flush()
        company = Company(owner_user_id=founder.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=founder.id, company_id=company.id, role=MembershipRole.founder))
        await data_policy.seed_default_labels(db, company.id)
        await db.commit()
        return company.id, founder.id


@requires_db
async def test_invite_is_consumed_on_authentication(session_factory):
    company_id, _ = await _company(session_factory)
    email = f"{uuid.uuid4()}@teammate.io"

    async with session_factory() as db:
        inv = await invites_svc.create_invite(
            db, company_id=company_id, email=email.upper(), labels=["customers", "marketing"]
        )
        await db.commit()
        assert inv.email == email.lower()  # normalised
        assert inv.role is MembershipRole.admin

    # The teammate authenticates for the first time -> membership materialises.
    async with session_factory() as db:
        user = User(email=email, hashed_password="x")
        db.add(user)
        await db.flush()
        accepted = await invites_svc.consume_for_user(db, user)
        await db.commit()
        assert accepted == 1
        m = await db.scalar(
            select(Membership).where(
                Membership.company_id == company_id, Membership.user_id == user.id
            )
        )
        assert m is not None and m.role is MembershipRole.admin
        assert set(m.access_labels) == {"customers", "marketing"}
        i = await db.scalar(select(CompanyInvite).where(CompanyInvite.id == inv.id))
        assert i.status is InviteStatus.accepted and i.accepted_user_id == user.id


@requires_db
async def test_consume_is_idempotent_for_existing_member(session_factory):
    company_id, _ = await _company(session_factory)
    email = f"{uuid.uuid4()}@t.io"
    async with session_factory() as db:
        user = User(email=email, hashed_password="x")
        db.add(user)
        await db.flush()
        db.add(Membership(user_id=user.id, company_id=company_id, role=MembershipRole.admin))
        await invites_svc.create_invite(db, company_id=company_id, email=email, labels=[])
        await db.commit()
        # Consuming when already a member marks the invite accepted without a dup.
        await invites_svc.consume_for_user(db, user)
        await db.commit()
        members = (
            await db.scalars(
                select(Membership).where(
                    Membership.company_id == company_id, Membership.user_id == user.id
                )
            )
        ).all()
        assert len(members) == 1


@requires_db
async def test_create_invite_validates(session_factory):
    company_id, _ = await _company(session_factory)
    async with session_factory() as db:
        for bad in ("", "not-an-email"):
            try:
                await invites_svc.create_invite(db, company_id=company_id, email=bad)
                raise AssertionError("expected InviteError")
            except invites_svc.InviteError:
                pass
        # Unknown label rejected.
        try:
            await invites_svc.create_invite(
                db, company_id=company_id, email="x@y.io", labels=["nope"]
            )
            raise AssertionError("expected InviteError")
        except data_policy.DataPolicyError:
            pass

    # Re-inviting the same pending address updates labels (no duplicate).
    async with session_factory() as db:
        a = await invites_svc.create_invite(db, company_id=company_id, email="dup@y.io", labels=["customers"])
        await db.commit()
        b = await invites_svc.create_invite(db, company_id=company_id, email="DUP@y.io", labels=["marketing"])
        await db.commit()
        assert a.id == b.id and b.access_labels == ["marketing"]


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
async def test_invite_endpoints_are_founder_controlled(session_factory):
    company_id, founder_id = await _company(session_factory)
    # A non-founder member to test the 403.
    async with session_factory() as db:
        other = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(other)
        await db.flush()
        db.add(Membership(user_id=other.id, company_id=company_id, role=MembershipRole.admin))
        await db.commit()
        other_id = other.id

    with _client() as client:
        base = f"/companies/{company_id}"
        # Founder invites, lists, and sees members.
        r = client.post(f"{base}/invites", headers=_auth(founder_id),
                        json={"email": "new@teammate.io", "access_labels": ["customers"]})
        assert r.status_code == 201 and r.json()["email"] == "new@teammate.io"
        invite_id = r.json()["id"]
        assert any(i["email"] == "new@teammate.io"
                   for i in client.get(f"{base}/invites", headers=_auth(founder_id)).json())
        assert client.get(f"{base}/members", headers=_auth(founder_id)).status_code == 200
        assert client.delete(f"{base}/invites/{invite_id}", headers=_auth(founder_id)).status_code == 204

        # A non-founder is forbidden everywhere.
        assert client.get(f"{base}/members", headers=_auth(other_id)).status_code == 403
        assert client.get(f"{base}/invites", headers=_auth(other_id)).status_code == 403
        assert client.post(f"{base}/invites", headers=_auth(other_id),
                           json={"email": "x@y.io"}).status_code == 403
