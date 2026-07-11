"""Reuse saved keys & connections from a founder's other businesses.

When a founder starts a new company, the keys/connections they configured on an
earlier company are offered for one-click reuse; selecting them copies the secret
(re-sealed) into the new company. Everything is scoped to the same owner, so a
different founder's credentials are never reachable.
"""

from __future__ import annotations

import base64
import os
import uuid

from app.models import Company, User
from app.models.enums import CompanyStatus
from app.services import apikeys, onboarding_reuse
from app.services import mcp as mcp_svc
from tests.conftest import requires_db


def _set_master_key() -> None:
    from app.config import settings as app_settings

    app_settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


async def _company(db, *, owner_id: uuid.UUID, name: str) -> Company:
    c = Company(owner_user_id=owner_id, name=name, status=CompanyStatus.active)
    db.add(c)
    await db.flush()
    return c


@requires_db
async def test_list_offers_keys_and_connections_from_other_companies(session_factory, monkeypatch):
    _set_master_key()
    monkeypatch.setattr(onboarding_reuse, "SessionLocal", session_factory)
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        source = await _company(db, owner_id=user.id, name="Alpha")
        target = await _company(db, owner_id=user.id, name="Beta")
        await apikeys.store_key(db, company_id=source.id, provider="anthropic", plaintext="sk-ant-abcd")
        await apikeys.store_key(db, company_id=source.id, provider="tavily", plaintext="tvly-1234")
        await mcp_svc.add_server(
            db, company_id=source.id, name="Acme CRM", label="Acme CRM", url="https://mcp.acme.test"
        )
        await db.commit()

        items = await onboarding_reuse.list_reusable(user_id=user.id, target_company_id=target.id)

    ids = {it["id"] for it in items}
    assert ids == {"key:anthropic", "key:tavily", "mcp:acme_crm"}
    # No secret ever leaks — the anthropic entry shows only a fingerprint.
    anthropic = next(it for it in items if it["id"] == "key:anthropic")
    assert anthropic["kind"] == "key"
    assert anthropic["source_company_name"] == "Alpha"
    assert "sk-ant-abcd" not in (anthropic["detail"] or "")


@requires_db
async def test_reuse_copies_selected_credentials_into_target(session_factory, monkeypatch):
    _set_master_key()
    monkeypatch.setattr(onboarding_reuse, "SessionLocal", session_factory)
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        source = await _company(db, owner_id=user.id, name="Alpha")
        target = await _company(db, owner_id=user.id, name="Beta")
        await apikeys.store_key(db, company_id=source.id, provider="anthropic", plaintext="sk-ant-secret")
        await mcp_svc.add_server(
            db, company_id=source.id, name="Acme CRM", label="Acme CRM", url="https://mcp.acme.test"
        )
        await db.commit()
        target_id = target.id

        reused = await onboarding_reuse.reuse(
            db, user_id=user.id, target_company_id=target_id, ids=["key:anthropic", "mcp:acme_crm"]
        )
        await db.commit()

    assert set(reused) == {"key:anthropic", "mcp:acme_crm"}
    async with session_factory() as db:
        # The key is present on the target and decrypts to the same plaintext.
        assert (
            await apikeys.get_plaintext_key(db, company_id=target_id, provider="anthropic")
            == "sk-ant-secret"
        )
        servers = await mcp_svc.list_servers(db, company_id=target_id)
        assert [s.name for s in servers] == ["acme_crm"]


@requires_db
async def test_reuse_is_scoped_to_the_owner(session_factory, monkeypatch):
    """A different founder's credentials are never listed or copied."""
    _set_master_key()
    monkeypatch.setattr(onboarding_reuse, "SessionLocal", session_factory)
    async with session_factory() as db:
        me = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        other = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add_all([me, other])
        await db.flush()
        their_company = await _company(db, owner_id=other.id, name="TheirCo")
        my_target = await _company(db, owner_id=me.id, name="MyNewCo")
        await apikeys.store_key(
            db, company_id=their_company.id, provider="anthropic", plaintext="sk-ant-theirs"
        )
        await db.commit()
        target_id = my_target.id

        items = await onboarding_reuse.list_reusable(user_id=me.id, target_company_id=target_id)
        assert items == []
        # Even naming the id explicitly copies nothing — the gather is owner-scoped.
        reused = await onboarding_reuse.reuse(
            db, user_id=me.id, target_company_id=target_id, ids=["key:anthropic"]
        )
        await db.commit()

    assert reused == []
    async with session_factory() as db:
        assert (
            await apikeys.get_plaintext_key(db, company_id=target_id, provider="anthropic") is None
        )


@requires_db
async def test_credentials_already_on_target_are_not_offered(session_factory, monkeypatch):
    _set_master_key()
    monkeypatch.setattr(onboarding_reuse, "SessionLocal", session_factory)
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        source = await _company(db, owner_id=user.id, name="Alpha")
        target = await _company(db, owner_id=user.id, name="Beta")
        await apikeys.store_key(db, company_id=source.id, provider="anthropic", plaintext="sk-src")
        # Target already has its own anthropic key -> nothing to reuse for it.
        await apikeys.store_key(db, company_id=target.id, provider="anthropic", plaintext="sk-tgt")
        await db.commit()

        items = await onboarding_reuse.list_reusable(user_id=user.id, target_company_id=target.id)

    assert items == []
