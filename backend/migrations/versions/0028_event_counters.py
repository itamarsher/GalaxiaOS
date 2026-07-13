"""Per-company event counters.

Adds the ``event_counters`` tenant table: one row per ``(company_id, event_type)``
holding a monotonic ``count`` and the timestamp of the most recent event. The
runtime increments these at its chokepoints so a company's activity totals are
available without scanning the detail tables.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this on a fresh DB, so create only if absent. RLS is
enabled to match every other tenant table (same policy shape as
``0002_row_level_security``).

Revision ID: 0028_event_counters
Revises: 0027_feature_request_agent_attr
Create Date: 2026-07-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0028_event_counters"
down_revision = "0027_feature_request_agent_attr"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
TABLE = "event_counters"

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

    if not insp.has_table(TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column(
                "company_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("event_type", sa.String(length=48), nullable=False),
            sa.Column("count", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column(
                "last_event_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            *_TIMESTAMPS,
            sa.UniqueConstraint(
                "company_id", "event_type", name="uq_event_counters_company_type"
            ),
        )
        op.create_index("ix_event_counters_company_id", TABLE, ["company_id"])
        op.create_index("ix_event_counters_event_type", TABLE, ["event_type"])

    _enable_rls(TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
