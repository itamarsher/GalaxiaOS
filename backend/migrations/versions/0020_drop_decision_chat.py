"""Drop the legacy per-decision discussion thread column.

The old "discuss this decision" interface (its own chat thread + agent Q&A on a
decision) has been removed — decisions now live entirely in the unified chat as
founder DMs. The ``decision_requests.chat`` JSONB column that backed that thread
is no longer read or written, so drop it.

Idempotent: only drops the column if it is present (the 0001 baseline builds the
schema from the ORM models via ``create_all``, which no longer defines it).

Revision ID: 0020_drop_decision_chat
Revises: 0019_feature_requests
Create Date: 2026-07-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0020_drop_decision_chat"
down_revision = "0019_feature_requests"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return any(c["name"] == column for c in insp.get_columns(table))


def upgrade() -> None:
    if _has_column("decision_requests", "chat"):
        op.drop_column("decision_requests", "chat")


def downgrade() -> None:
    if not _has_column("decision_requests", "chat"):
        op.add_column(
            "decision_requests",
            sa.Column("chat", JSONB(), nullable=True),
        )
