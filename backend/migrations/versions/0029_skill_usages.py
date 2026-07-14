"""Skill-usage telemetry.

Adds the ``skill_usages`` tenant table: one row per ``load_skill`` call recording
which task/agent pulled which skill (by slug). Completed tasks drop their
transcript at terminal state, so this is the durable link from a task's outcome
back to the skill it used — the signal the skill optimizer learns from.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this on a fresh DB, so create only if absent. RLS is
enabled to match every other tenant table (same policy shape as
``0002_row_level_security`` / ``0028_event_counters``).

Revision ID: 0029_skill_usages
Revises: 0028_event_counters
Create Date: 2026-07-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0029_skill_usages"
down_revision = "0028_event_counters"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
TABLE = "skill_usages"

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
                "task_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "agent_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("skill_name", sa.String(length=120), nullable=False),
            *_TIMESTAMPS,
        )
        op.create_index("ix_skill_usages_company_id", TABLE, ["company_id"])
        op.create_index("ix_skill_usages_task_id", TABLE, ["task_id"])
        op.create_index("ix_skill_usages_agent_id", TABLE, ["agent_id"])
        op.create_index("ix_skill_usages_skill_name", TABLE, ["skill_name"])

    _enable_rls(TABLE)


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {TABLE}")
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY")
    op.execute(f"DROP TABLE IF EXISTS {TABLE}")
