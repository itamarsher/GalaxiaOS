"""Add ``tasks.transcript`` — durable working memory for in-flight tasks.

The native agent loop checkpoints its multi-turn conversation here after every
step so a task orphaned by a restart resumes where it left off (see
``app.jobs.recovery`` + ``NativeBackend``) instead of re-running from scratch.
The column is cleared to NULL when the task reaches a terminal state, so it only
ever holds live tasks' turns and does not grow into a permanent message log.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this column on a fresh DB, so add it only if
absent. ``tasks`` already has its RLS policy from earlier migrations; adding a
column does not change that.

Revision ID: 0004_task_transcript
Revises: 0003_metrics_investment
Create Date: 2026-06-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_task_transcript"
down_revision = "0003_metrics_investment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {col["name"] for col in insp.get_columns("tasks")}
    if "transcript" not in columns:
        op.add_column("tasks", sa.Column("transcript", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "transcript")
