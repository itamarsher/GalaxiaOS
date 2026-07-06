"""Phase 5 tests: per-company provider resolution and active RLS tenant isolation."""

from __future__ import annotations

import base64
import os
import uuid

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.providers.registry import get_provider
from tests.conftest import TEST_DB_URL, requires_db

# ── #1 provider selection ─────────────────────────────────────────────────────


def test_providers_expose_default_model_tiers():
    for name in ("anthropic", "openai"):
        models = get_provider(name).default_models
        assert {"cheap", "planner", "strategic"} <= set(models)
        assert all(isinstance(v, str) and v for v in models.values())


@requires_db
async def test_resolve_provider_picks_configured_provider(session_factory):
    # Envelope encryption needs a master key; set one on the cached settings.
    from app.config import settings as app_settings

    app_settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()

    from app.models import Company, User
    from app.models.enums import CompanyStatus
    from app.services import apikeys

    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        cid = company.id

        # Configure Anthropic first, then OpenAI in a later transaction; the most
        # recently added key selects the provider (distinct created_at timestamps).
        await apikeys.store_key(db, company_id=cid, provider="anthropic", plaintext="sk-ant-xxxx")
        await db.commit()
        await apikeys.store_key(db, company_id=cid, provider="openai", plaintext="sk-oai-yyyy")
        await db.commit()

        resolved = await apikeys.resolve_provider(db, company_id=cid)
        assert resolved is not None
        provider, key = resolved
        assert provider.name == "openai"
        assert key == "sk-oai-yyyy"


# ── #2 RLS isolation ──────────────────────────────────────────────────────────


@requires_db
async def test_rls_policy_isolates_by_tenant_guc(session_factory):
    """The permissive-until-set policy: unset GUC sees all rows; a set GUC scopes
    to that tenant. Verified through a non-superuser role (the owner/superuser
    bypasses RLS), exactly as the app role behaves in production."""
    company_a, company_b = uuid.uuid4(), uuid.uuid4()
    policy = (
        "CREATE POLICY p ON rls_demo USING ("
        "current_setting('app.current_company', true) IS NULL "
        "OR current_setting('app.current_company', true) = '' "
        "OR company_id = current_setting('app.current_company', true)::uuid)"
    )
    async with session_factory() as db:
        await db.execute(text("DROP TABLE IF EXISTS rls_demo"))
        await db.execute(text("CREATE TABLE rls_demo (id serial primary key, company_id uuid)"))
        await db.execute(text("ALTER TABLE rls_demo ENABLE ROW LEVEL SECURITY"))
        await db.execute(text(policy))
        await db.execute(text("DROP ROLE IF EXISTS rls_test_role"))
        await db.execute(text("CREATE ROLE rls_test_role LOGIN PASSWORD 'pw'"))
        await db.execute(text("GRANT SELECT ON rls_demo TO rls_test_role"))
        await db.execute(
            text("INSERT INTO rls_demo (company_id) VALUES (:a), (:b)"),
            {"a": str(company_a), "b": str(company_b)},
        )
        await db.commit()

    role_engine = create_async_engine(
        make_url(TEST_DB_URL).set(username="rls_test_role", password="pw")
    )
    try:
        async with role_engine.connect() as conn:
            # No GUC set -> permissive -> both rows visible.
            assert (await conn.scalar(text("SELECT count(*) FROM rls_demo"))) == 2
            # Scope to company A within this transaction -> only A's row.
            await conn.execute(
                text("SELECT set_config('app.current_company', :c, true)"),
                {"c": str(company_a)},
            )
            assert (await conn.scalar(text("SELECT count(*) FROM rls_demo"))) == 1
    finally:
        await role_engine.dispose()
        async with session_factory() as db:
            await db.execute(text("DROP TABLE IF EXISTS rls_demo"))
            await db.execute(text("DROP ROLE IF EXISTS rls_test_role"))
            await db.commit()
