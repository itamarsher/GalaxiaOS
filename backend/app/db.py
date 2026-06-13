"""Async database engine and session factory.

Multi-tenancy (the ``company_id`` boundary) is enforced today at the
service/query layer. As defense-in-depth, the schema also has Postgres
Row-Level Security (RLS) enabled on every tenant table (migration
``0002_row_level_security``), keyed to the ``app.current_company`` session GUC.

Permissive-until-adopted rollout
--------------------------------
The RLS policy is *permissive when the GUC is unset/empty*: a connection that
never sets ``app.current_company`` sees all rows, exactly as before. So
``get_db`` stays unchanged and non-tenant routes / tests keep working without
opting in.

To opt a request into DB-level tenant scoping, call :func:`set_tenant` after
acquiring the session (e.g. from the tenant dependency once a company is
resolved)::

    async def get_scoped_db(company: CompanyDep, db: DbDep) -> AsyncSession:
        await set_tenant(db, company.id)
        return db

``set_tenant`` sets the GUC at transaction (``LOCAL``) scope, so it is
automatically cleared on commit/rollback — never leaking to the next checkout
of a pooled connection.

Making RLS strict (final step)
------------------------------
Once *every* tenant-touching route resolves a company and calls
:func:`set_tenant`, ship a follow-up migration that replaces the permissive
policy with a strict one::

    USING (company_id = current_setting('app.current_company')::uuid)

(no ``true`` second arg, so an unset GUC raises instead of leaking). That flips
RLS from a safety net into a hard, enforced boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

#: Postgres session GUC the RLS policies read to scope rows to one tenant.
TENANT_GUC = "app.current_company"


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a request-scoped async session."""
    async with SessionLocal() as session:
        yield session


async def set_tenant(session: AsyncSession, company_id: uuid.UUID | str) -> None:
    """Scope ``session`` to one tenant for the RLS policies (opt-in).

    Sets the ``app.current_company`` GUC at transaction (``LOCAL``) scope so the
    ``0002_row_level_security`` policies filter to this company. We use
    ``set_config(name, value, is_local := true)`` rather than ``SET LOCAL``
    because ``SET`` cannot take a bound parameter for its value; ``set_config``
    can, which keeps the company id safely parameterized. ``is_local := true``
    means the value is transaction-scoped and cleared on commit/rollback, so it
    never leaks to another checkout of a pooled connection.

    Calling this is optional: while the policies are permissive, sessions that
    never call it behave exactly as before (see module docstring).
    """
    await session.execute(
        text("SELECT set_config(:guc, :company_id, true)"),
        {"guc": TENANT_GUC, "company_id": str(company_id)},
    )
