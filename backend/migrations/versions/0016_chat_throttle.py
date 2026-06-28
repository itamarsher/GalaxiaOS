"""Throttle runaway chat loops with a CEO-extendable message budget.

Distributed agent collaboration happens in shared chat channels (see
:mod:`app.services.chat`). To stop two agents from ping-ponging replies forever,
each channel carries a ``message_budget`` — the number of messages it may hold
before the next post escalates to the CEO — and an ``escalation_pending`` flag
that pauses posting while that CEO review is open. The CEO grants the next
allowance with ``extend_chat_channel``, so a productive discussion keeps going
while a runaway one is caught.

Additive and idempotent: add each column only if absent. Existing channels get
the default budget and a cleared escalation flag via server defaults.

Revision ID: 0016_chat_throttle
Revises: 0015_decision_channel
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_chat_throttle"
down_revision = "0015_decision_channel"
branch_labels = None
depends_on = None

TABLE = "chat_channels"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    if "message_budget" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "message_budget",
                sa.Integer(),
                nullable=False,
                server_default="10",
            ),
        )
    if "escalation_pending" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "escalation_pending",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )


def downgrade() -> None:
    op.drop_column(TABLE, "escalation_pending")
    op.drop_column(TABLE, "message_budget")
