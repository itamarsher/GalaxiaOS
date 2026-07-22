"""Test fixtures.

The budget/metering tests need real ``SELECT ... FOR UPDATE`` semantics, so they
run against Postgres. Set ``ABOS_TEST_DATABASE_URL`` (asyncpg URL) to enable
them; otherwise they are skipped. A separate schema is created/dropped per run.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base, Budget, Company, Membership, Mission, User
from app.models.enums import BudgetPeriod, CompanyStatus, MembershipRole

TEST_DB_URL = os.getenv("ABOS_TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(TEST_DB_URL is None, reason="ABOS_TEST_DATABASE_URL not set")


async def make_company_with_fleet(db, *, is_platform: bool = True):
    """Create a user + company (+ budget, mission, founder membership) and provision
    the default fleet (no LLM), returning the company id.

    Replaces the old ``galaxia._run`` test scaffolding now that the dogfooding
    company is a normal onboarded company: tests that need a fully-provisioned org
    (with a CEO + oversight roles) call this, passing ``is_platform`` to designate
    the platform company for gate tests.
    """
    from app.services.onboarding import _fleet_specs, provision_fleet

    user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(
        owner_user_id=user.id,
        name="Platform Co" if is_platform else "T",
        status=CompanyStatus.active,
    )
    db.add(company)
    await db.flush()
    if is_platform:
        # Designate this company as the operator via config (no more magic flag).
        from app.config import settings

        settings.platform_company_id = str(company.id)
    db.add(Membership(user_id=user.id, company_id=company.id, role=MembershipRole.founder))
    db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=50_000))
    mission = Mission(company_id=company.id, raw_text="Dogfood the product", constraints=[])
    db.add(mission)
    await db.flush()
    company.mission_id = mission.id
    await provision_fleet(
        db, company=company, specs=_fleet_specs([]), total_budget_cents=50_000
    )
    await db.flush()
    return company.id


@pytest.fixture(autouse=True)
def _reset_operator_company():
    """No operator company by default — each test that wants one designates it
    (helpers set ``settings.platform_company_id`` when ``is_platform=True``)."""
    from app.config import settings

    settings.platform_company_id = ""


@pytest.fixture(autouse=True)
def _offline_embedder(monkeypatch):
    """Keep Company Memory offline in tests.

    The default embeddings provider is ``local`` (a real fastembed model). Pin the
    embedder to the dependency-free hashing one for the suite so no test downloads
    or runs a neural model. Tests that exercise a specific embedder override this
    with their own monkeypatch (applied after this autouse fixture).
    """
    from app.services import embeddings

    monkeypatch.setattr(embeddings, "_embedder", embeddings.HashingEmbedder())


# Every table except the pgvector-backed one, so the suite runs on a plain
# Postgres without the `vector` extension installed (CI uses pgvector/pgvector).
_TABLES = [t for name, t in Base.metadata.tables.items() if name != "memory_entries"]


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(TEST_DB_URL, future=True)
    async with engine.begin() as conn:
        # Hard reset to a clean schema. This is robust whether the DB is empty
        # or already migrated by CI's `alembic upgrade head` — the latter leaves
        # `memory_entries` (FK -> tasks) and RLS policies that a partial
        # ``drop_all`` can't remove. Dropping the schema sidesteps all of that.
        await conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        await conn.exec_driver_sql("CREATE SCHEMA public")
        # Recreating the schema drops the default PUBLIC grants; restore them so
        # the RLS test's non-owner role can USAGE the schema (an unqualified name
        # in an inaccessible schema reports "does not exist", not "denied").
        await conn.exec_driver_sql("GRANT USAGE, CREATE ON SCHEMA public TO PUBLIC")
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield sf
    await engine.dispose()


@pytest_asyncio.fixture
async def company_with_budget(session_factory):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(
            Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=10_000)
        )
        await db.commit()
        return company.id
