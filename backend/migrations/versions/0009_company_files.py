"""Company files — the external file-store manifest.

Adds one tenant table backing the file provider (Google Drive today): a durable,
queryable record of every document filed under ``.abos/<company>/<Category>/`` so
the store stays auditable and listable from the database even when the external
provider is unreachable.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this on a fresh DB, so create only if absent. RLS is
enabled to match every other tenant table (same policy shape as
``0002_row_level_security`` / ``0006_crm`` / ``0007_sites``).

Revision ID: 0009_company_files
Revises: 0008_company_email_from
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0009_company_files"
down_revision = "0008_company_email_from"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
_TABLE = "company_files"

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

    if not insp.has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column(
                "company_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("category", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("mime_type", sa.String(length=120), nullable=False),
            sa.Column("folder_path", sa.String(length=512), nullable=False),
            sa.Column("provider", sa.String(length=60), nullable=False),
            sa.Column("external_id", sa.String(length=255), nullable=True),
            sa.Column("web_url", sa.String(length=1024), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=True),
            sa.Column(
                "source_task_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            *_TIMESTAMPS,
        )
        op.create_index("ix_company_files_company_id", _TABLE, ["company_id"])
        op.create_index("ix_company_files_category", _TABLE, ["category"])
        op.create_index("ix_company_files_name", _TABLE, ["name"])

    _enable_rls(_TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {_TABLE}")
    op.execute(f"ALTER TABLE {_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP TABLE IF EXISTS {_TABLE}")
