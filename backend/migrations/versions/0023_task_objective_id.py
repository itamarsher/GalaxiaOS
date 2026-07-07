"""Add tasks.objective_id — the explicit objective a task serves.

The CEO tags each dispatched initiative with the objective it advances, and
sub-tasks inherit it. Objective completion and the founder's quest board read
this link directly, replacing the old keyword-overlap heuristic that guessed
which objective a task belonged to.

Additive and idempotent: the 0001 baseline builds the schema from the ORM models
via ``create_all``, so add the column/FK/index only if absent.

Revision ID: 0023_task_objective_id
Revises: 0022_clear_ceo_budget_cap
Create Date: 2026-07-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0023_task_objective_id"
down_revision = "0022_clear_ceo_budget_cap"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(c["name"] == column for c in insp.get_columns(table))


def _has_index(table: str, name: str) -> bool:
    insp = sa.inspect(op.get_bind())
    return any(ix["name"] == name for ix in insp.get_indexes(table))


def upgrade() -> None:
    if not _has_column("tasks", "objective_id"):
        op.add_column(
            "tasks",
            sa.Column(
                "objective_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("objectives.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if not _has_index("tasks", "ix_tasks_objective_id"):
        op.create_index("ix_tasks_objective_id", "tasks", ["objective_id"])


def downgrade() -> None:
    if _has_index("tasks", "ix_tasks_objective_id"):
        op.drop_index("ix_tasks_objective_id", table_name="tasks")
    if _has_column("tasks", "objective_id"):
        op.drop_column("tasks", "objective_id")
