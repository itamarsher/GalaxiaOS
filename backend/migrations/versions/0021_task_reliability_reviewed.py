"""Add tasks.reliability_reviewed_at — the reliability monitor's watermark.

Galaxia's reliability monitor scans its own failed tasks and wakes the Platform
agent to investigate each one. This column marks a failed task as already picked
up, so it is investigated exactly once (and investigation tasks are pre-stamped so
they never investigate themselves).

Additive and idempotent: the 0001 baseline builds the schema from the ORM models
via ``create_all``, so add the column only if it is absent.

Revision ID: 0021_task_reliability_reviewed
Revises: 0020_drop_decision_chat
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_task_reliability_reviewed"
down_revision = "0020_drop_decision_chat"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if not _has_column("tasks", "reliability_reviewed_at"):
        op.add_column(
            "tasks",
            sa.Column("reliability_reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    if _has_column("tasks", "reliability_reviewed_at"):
        op.drop_column("tasks", "reliability_reviewed_at")
