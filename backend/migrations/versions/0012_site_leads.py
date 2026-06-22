"""Site leads — early-signal/waitlist signups captured by landing pages.

Adds one tenant table, ``site_leads``, storing email signups submitted through a
published landing page's built-in capture form. The page is static and hosted
off-platform, so it POSTs to a public API endpoint that writes a row here (and
also funnels the person into the CRM as a contact).

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this on a fresh DB, so create only if absent. RLS is
enabled to match every other tenant table (same policy shape as
``0002_row_level_security`` / ``0007_sites``).

Revision ID: 0012_site_leads
Revises: 0011_external_messages
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0012_site_leads"
down_revision = "0011_external_messages"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
_NEW_TABLES = ("site_leads",)

_TIMESTAMPS = (
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    ),
)


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    op.execute(
        f"CREATE POLICY {POLICY} ON {table} "
        "USING ("
        f"current_setting('{GUC}', true) IS NULL "
        f"OR current_setting('{GUC}', true) = '' "
        f"OR company_id = current_setting('{GUC}', true)::uuid"
        ") WITH CHECK ("
        f"current_setting('{GUC}', true) IS NULL "
        f"OR current_setting('{GUC}', true) = '' "
        f"OR company_id = current_setting('{GUC}', true)::uuid"
        ")"
    )


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("site_leads"):
        op.create_table(
            "site_leads",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column(
                "company_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "site_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("sites.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("email", sa.String(length=320), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("source", sa.String(length=255), nullable=True),
            *_TIMESTAMPS,
        )
        op.create_index("ix_site_leads_company_id", "site_leads", ["company_id"])
        op.create_index("ix_site_leads_site_id", "site_leads", ["site_id"])
        op.create_index("ix_site_leads_email", "site_leads", ["email"])

    for table in _NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS site_leads")
