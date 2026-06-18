"""Sites + connected domains — landing-page hosting and domain connection.

Adds two tenant tables backing the "build a page -> host it -> connect a bought
domain" pipeline:
- ``sites`` — generated landing pages (markdown body + rendered HTML) and their
  live host URL.
- ``site_domains`` — bought domains being connected to a site, plus the DNS-zone /
  nameserver bookkeeping for the connection state machine.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds these on a fresh DB, so create only if absent. RLS is
enabled to match every other tenant table (same policy shape as
``0002_row_level_security`` / ``0006_crm``).

Revision ID: 0007_sites
Revises: 0006_crm
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0007_sites"
down_revision = "0006_crm"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
_NEW_TABLES = ("sites", "site_domains")

_TIMESTAMPS = (
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    ),
)


def _company_fk() -> sa.Column:
    return sa.Column(
        "company_id",
        PGUUID(as_uuid=True),
        sa.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
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

    if not insp.has_table("sites"):
        op.create_table(
            "sites",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column("slug", sa.String(length=255), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("html", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
            sa.Column("provider", sa.String(length=60), nullable=True),
            sa.Column("project_name", sa.String(length=120), nullable=True),
            sa.Column("deployment_url", sa.String(length=512), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            *_TIMESTAMPS,
        )
        op.create_index("ix_sites_company_id", "sites", ["company_id"])
        op.create_index("ix_sites_slug", "sites", ["slug"])
        op.create_index("ix_sites_status", "sites", ["status"])

    if not insp.has_table("site_domains"):
        op.create_table(
            "site_domains",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column(
                "site_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("sites.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("domain", sa.String(length=253), nullable=False),
            sa.Column("provider", sa.String(length=60), nullable=True),
            sa.Column("zone_id", sa.String(length=120), nullable=True),
            sa.Column("nameservers", JSONB(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending_ns"),
            sa.Column("last_error", sa.Text(), nullable=True),
            *_TIMESTAMPS,
        )
        op.create_index("ix_site_domains_company_id", "site_domains", ["company_id"])
        op.create_index("ix_site_domains_site_id", "site_domains", ["site_id"])
        op.create_index("ix_site_domains_domain", "site_domains", ["domain"])
        op.create_index("ix_site_domains_status", "site_domains", ["status"])

    for table in _NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS site_domains")
    op.execute("DROP TABLE IF EXISTS sites")
