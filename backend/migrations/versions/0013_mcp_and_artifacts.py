"""MCP servers + founder-facing artifacts.

Adds two tenant tables:
- ``mcp_servers`` — founder-connected MCP tool servers (URL/transport in plain
  columns; the optional bearer token envelope-encrypted; a cache of the tools the
  server exposes).
- ``artifacts`` — founder-facing deliverables (investor updates, growth/research
  reports, board briefs) agents file via ``create_report`` or the founder
  generates on demand.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds these on a fresh DB, so create only if absent. RLS is
enabled to match every other tenant table (same policy shape as
``0007_sites`` / ``0006_crm``).

Revision ID: 0013_mcp_and_artifacts
Revises: 0012_site_leads
Create Date: 2026-06-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0013_mcp_and_artifacts"
down_revision = "0012_site_leads"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
_NEW_TABLES = ("mcp_servers", "artifacts")

_TIMESTAMPS = (
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
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

    if not insp.has_table("mcp_servers"):
        op.create_table(
            "mcp_servers",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column("name", sa.String(length=64), nullable=False),
            sa.Column("label", sa.String(length=255), nullable=False),
            sa.Column("url", sa.String(length=1024), nullable=False),
            sa.Column("transport", sa.String(length=20), nullable=False, server_default="http"),
            sa.Column("encrypted_auth", sa.LargeBinary(), nullable=True),
            sa.Column("encrypted_data_key", sa.LargeBinary(), nullable=True),
            sa.Column("nonce", sa.LargeBinary(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("tools_cache", JSONB(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            *_TIMESTAMPS,
        )
        op.create_index("ix_mcp_servers_company_id", "mcp_servers", ["company_id"])

    if not insp.has_table("artifacts"):
        op.create_table(
            "artifacts",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column("kind", sa.String(length=40), nullable=False, server_default="custom"),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body_md", sa.Text(), nullable=False),
            sa.Column("source_task_id", PGUUID(as_uuid=True), nullable=True),
            sa.Column("source_agent_id", PGUUID(as_uuid=True), nullable=True),
            sa.Column("extra", JSONB(), nullable=True),
            *_TIMESTAMPS,
        )
        op.create_index("ix_artifacts_company_id", "artifacts", ["company_id"])

    for table in _NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    op.drop_table("artifacts")
    op.drop_table("mcp_servers")
