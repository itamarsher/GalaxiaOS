"""Link decisions to their founder DM channel.

Part of consolidating the decision inbox into chat: every decision now surfaces
as a direct message to the founder marked "waiting for a response" (see
:mod:`app.services.chat`). This adds ``decision_requests.channel_id`` so a
structured decision (the kind that carries an approval grant or budget lift) is
joined to the chat thread it lives in, letting resolution post back into the
conversation.

Additive and idempotent: add the column only if absent. The chat tables it
references are created in ``0014_chat``.

Revision ID: 0015_decision_channel
Revises: 0014_chat
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0015_decision_channel"
down_revision = "0014_chat"
branch_labels = None
depends_on = None

TABLE = "decision_requests"
COLUMN = "channel_id"


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(TABLE)}
    if COLUMN not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                PGUUID(as_uuid=True),
                sa.ForeignKey("chat_channels.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    op.drop_column(TABLE, COLUMN)
