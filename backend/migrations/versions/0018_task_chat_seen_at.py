"""Add tasks.chat_seen_at — the watermark for the "new chat to catch up on" nudge.

The agent loop nudges a task to read new chat activity in the channels it belongs
to — on resume (messages that arrived while it was parked) and while it's running.
This column records the timestamp of the most recent chat message the task has
already been told about, so each new batch nudges exactly once.

Additive and idempotent: add the column only if absent. NULL means "no baseline
yet" (the loop sets it on the task's first step without nudging).

Revision ID: 0018_task_chat_seen_at
Revises: 0017_chat_threads
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_task_chat_seen_at"
down_revision = "0017_chat_threads"
branch_labels = None
depends_on = None

TABLE = "tasks"
COLUMN = "chat_seen_at"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    if COLUMN not in cols:
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
