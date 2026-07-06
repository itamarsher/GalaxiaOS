"""Threads inside channels: named sub-conversations for parallel sub-initiatives.

A channel coordinates a whole initiative; a thread carves out one strand of it so
several agents can multitask on parallel sub-topics without colliding in a single
timeline (see :mod:`app.services.chat`). Adds the ``chat_threads`` table and the
``thread_id`` scope column on ``chat_messages`` and ``chat_waits`` (NULL = the
channel's main timeline). Each thread carries its own loop-guard budget, so a
runaway strand escalates on its own without pausing the rest of the channel.

Additive and idempotent: create the table and add each column only if absent.

Revision ID: 0017_chat_threads
Revises: 0016_chat_throttle
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0017_chat_threads"
down_revision = "0016_chat_throttle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "chat_threads" not in tables:
        op.create_table(
            "chat_threads",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column("company_id", PGUUID(as_uuid=True), nullable=False, index=True),
            sa.Column(
                "channel_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("chat_channels.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column(
                "created_by_agent_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("message_budget", sa.Integer(), nullable=False, server_default="10"),
            sa.Column(
                "escalation_pending", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    for table in ("chat_messages", "chat_waits"):
        cols = {c["name"] for c in insp.get_columns(table)}
        if "thread_id" not in cols:
            op.add_column(
                table,
                sa.Column(
                    "thread_id",
                    PGUUID(as_uuid=True),
                    sa.ForeignKey("chat_threads.id", ondelete="CASCADE"),
                    nullable=True,
                ),
            )
            op.create_index(
                f"ix_{table}_thread_id", table, ["thread_id"]
            )


def downgrade() -> None:
    for table in ("chat_waits", "chat_messages"):
        op.drop_index(f"ix_{table}_thread_id", table_name=table)
        op.drop_column(table, "thread_id")
    op.drop_table("chat_threads")
