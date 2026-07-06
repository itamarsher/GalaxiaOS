"""Add ``decision_requests.chat`` — persisted founder↔agent discussion thread.

The decision discussion used to live only in the browser, so the agent lost the
back-and-forth between messages and the founder lost it on reload. Storing the
thread here (a list of ``{"who", "text"}`` turns) makes it durable and lets the
agent answer with the full conversation in context.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this column on a fresh DB, so add it only if
absent. ``decision_requests`` keeps its existing RLS policy; adding a column
does not change it.

Revision ID: 0005_decision_chat
Revises: 0004_task_transcript
Create Date: 2026-06-17
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_decision_chat"
down_revision = "0004_task_transcript"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {col["name"] for col in insp.get_columns("decision_requests")}
    if "chat" not in columns:
        op.add_column("decision_requests", sa.Column("chat", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("decision_requests", "chat")
