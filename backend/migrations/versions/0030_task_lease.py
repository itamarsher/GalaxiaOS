"""Claim lease on tasks for the async-first initiative lifecycle.

Adds a nullable ``lease_expires_at`` column to ``tasks``. It is set when a *pull*
worker claims an initiative (``queued`` -> ``running``) so a dead or slow worker's
lease can expire and the initiative be reassigned (RFC 0001, migration step 3).
Push-run (native) tasks leave it NULL and are never lease-reclaimed.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this column on a fresh DB, so add it only if absent.

Revision ID: 0030_task_lease
Revises: 0029_skill_usages
Create Date: 2026-07-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0030_task_lease"
down_revision = "0029_skill_usages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("tasks")}
    if "lease_expires_at" not in columns:
        op.add_column(
            "tasks",
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("tasks", "lease_expires_at")
