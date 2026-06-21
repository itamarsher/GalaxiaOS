"""Outbound external-communication index.

Adds the ``external_messages`` tenant table: a durable record of every message an
agent attempts to send outside the company (email, social post, published page,
ad, notification), written at the agent loop's tool chokepoint. It also backs the
"every external communication needs founder approval" policy — a gated message is
parked here as ``pending_approval`` and linked to its ``decision_requests`` row.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this on a fresh DB, so create only if absent. RLS is
enabled to match every other tenant table (same policy shape as
``0002_row_level_security``).

Revision ID: 0011_external_messages
Revises: 0010_company_playbook
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0011_external_messages"
down_revision = "0010_company_playbook"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
TABLE = "external_messages"

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
            sa.Column(
                "agent_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "task_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "decision_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("decision_requests.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("tool", sa.String(length=64), nullable=False),
            sa.Column("channel", sa.String(length=40), nullable=False),
            sa.Column("recipient", sa.String(length=500), nullable=True),
            sa.Column("subject", sa.String(length=500), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("payload", JSONB(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="sent"),
            sa.Column("detail", sa.Text(), nullable=True),
            *_TIMESTAMPS,
        )
        op.create_index(
            "ix_external_messages_company_id", TABLE, ["company_id"]
        )
        op.create_index("ix_external_messages_task_id", TABLE, ["task_id"])
        op.create_index("ix_external_messages_channel", TABLE, ["channel"])
        op.create_index("ix_external_messages_status", TABLE, ["status"])

    _enable_rls(TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
