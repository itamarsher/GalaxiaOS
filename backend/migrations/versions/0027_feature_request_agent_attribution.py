"""Feature-request votes: attribute the requesting agent (and its task).

Adds ``agent_id`` + ``task_id`` to ``feature_request_votes`` so the platform can
see *which agent* (not just which company/user) asked for a capability, and so a
delivered capability can be routed back to the agent that requested it. The vote
uniqueness constraint gains ``agent_id`` so two distinct agents in one company
each register their own demand (previously all agent-initiated asks in a company
collapsed to a single ``user_id IS NULL`` vote).

Additive and idempotent: the 0001 baseline ``create_all`` already builds the new
shape on a fresh DB, so guard each step on the current column/constraint set.

Revision ID: 0027_feature_request_agent_attr
Revises: 0026_user_sso_platform_company
Create Date: 2026-07-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0027_feature_request_agent_attr"
down_revision = "0026_user_sso_platform_company"
branch_labels = None
depends_on = None

TABLE = "feature_request_votes"


def _columns(insp) -> set[str]:
    return {c["name"] for c in insp.get_columns(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(TABLE):
        return  # fresh DB: baseline create_all already made the new shape

    cols = _columns(insp)
    if "agent_id" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "agent_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_feature_request_votes_agent_id", TABLE, ["agent_id"])
    if "task_id" not in cols:
        op.add_column(
            TABLE,
            sa.Column(
                "task_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("tasks.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # Widen the uniqueness constraint to include agent_id so distinct agents in one
    # company each hold their own vote. Drop-then-create so a re-run is safe.
    op.execute(
        "ALTER TABLE feature_request_votes DROP CONSTRAINT IF EXISTS uq_feature_request_vote"
    )
    op.create_unique_constraint(
        "uq_feature_request_vote",
        TABLE,
        ["feature_request_id", "company_id", "user_id", "agent_id"],
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE feature_request_votes DROP CONSTRAINT IF EXISTS uq_feature_request_vote"
    )
    op.create_unique_constraint(
        "uq_feature_request_vote",
        TABLE,
        ["feature_request_id", "company_id", "user_id"],
    )
    op.drop_index("ix_feature_request_votes_agent_id", table_name=TABLE)
    op.drop_column(TABLE, "task_id")
    op.drop_column(TABLE, "agent_id")
