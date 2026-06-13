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

from app.models import Base, Budget, Company, User
from app.models.enums import BudgetPeriod, CompanyStatus

TEST_DB_URL = os.getenv("ABOS_TEST_DATABASE_URL")
requires_db = pytest.mark.skipif(TEST_DB_URL is None, reason="ABOS_TEST_DATABASE_URL not set")


# Every table except the pgvector-backed one, so the suite runs on a plain
# Postgres without the `vector` extension installed (CI uses pgvector/pgvector).
_TABLES = [t for name, t in Base.metadata.tables.items() if name != "memory_entries"]


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine(TEST_DB_URL, future=True)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=_TABLES))
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=_TABLES))
    sf = async_sessionmaker(engine, expire_on_commit=False)
    yield sf
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=_TABLES))
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
