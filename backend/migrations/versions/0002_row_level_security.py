"""Row-Level Security as defense-in-depth on every tenant table.

Tenancy is already enforced at the service/query layer (filtering by the
``company_id`` resolved in ``CompanyDep``). This migration adds a second,
database-level guardrail: Postgres Row-Level Security (RLS) keyed to a session
GUC, ``app.current_company``.

SAFETY — permissive until adopted
---------------------------------
The policy is intentionally *permissive when the GUC is unset or empty* so that
existing code paths and tests that never set the GUC keep working unchanged::

    USING (
        current_setting('app.current_company', true) IS NULL
        OR current_setting('app.current_company', true) = ''
        OR company_id = current_setting('app.current_company', true)::uuid
    )

The app connects as the table *owner*, and owners bypass RLS by default, so we
also issue ``FORCE ROW LEVEL SECURITY`` to make the policy apply to the owner.
Even with FORCE, the permissive clause above means a connection that never sets
``app.current_company`` sees all rows (i.e. behaves exactly as today).

Once every tenant-touching route sets the GUC (see ``app.db.set_tenant``), a
follow-up migration can replace the policy with a strict one::

    USING (company_id = current_setting('app.current_company')::uuid)

(note: no ``true`` 2nd arg -> errors if unset, which is the goal once adopted).

The tenant table list is derived from the ORM metadata (every table carrying a
``company_id`` column) so it stays in sync as models change.

Revision ID: 0002_row_level_security
Revises: 0001_initial
Create Date: 2026-06-13
"""

from __future__ import annotations

from alembic import op

from app.models import Base

revision = "0002_row_level_security"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"


def _tenant_tables() -> list[str]:
    """Tables that carry the ``company_id`` tenant boundary, from ORM metadata."""
    return sorted(
        table.name
        for table in Base.metadata.tables.values()
        if "company_id" in table.columns
    )


def upgrade() -> None:
    for table in _tenant_tables():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE so the policy also applies to the table owner (the app role),
        # which would otherwise bypass RLS entirely.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {POLICY} ON {table} "
            "USING ("
            f"current_setting('{GUC}', true) IS NULL "
            f"OR current_setting('{GUC}', true) = '' "
            f"OR company_id = current_setting('{GUC}', true)::uuid"
            ") "
            "WITH CHECK ("
            f"current_setting('{GUC}', true) IS NULL "
            f"OR current_setting('{GUC}', true) = '' "
            f"OR company_id = current_setting('{GUC}', true)::uuid"
            ")"
        )


def downgrade() -> None:
    for table in _tenant_tables():
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
