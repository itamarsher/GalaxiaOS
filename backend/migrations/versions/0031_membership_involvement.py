"""Per-person involvement preferences on memberships.

Adds three nullable columns to ``memberships`` for the human-binding model (RFC
0001): ``involvement`` (the active, founder-sanctioned prose the involvement router
reads), ``proposed_involvement`` (a teammate's pending proposal awaiting founder
approval — never read by the router, so a teammate can't self-escalate), and
``coverage`` (an optional area/function focus prior). Replaces the old global
autonomy scale with per-person, natural-language preferences.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds these columns on a fresh DB, so add them only if
absent.

Revision ID: 0031_membership_involvement
Revises: 0030_task_lease
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031_membership_involvement"
down_revision = "0030_task_lease"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("memberships")}
    if "involvement" not in columns:
        op.add_column("memberships", sa.Column("involvement", sa.Text(), nullable=True))
    if "proposed_involvement" not in columns:
        op.add_column("memberships", sa.Column("proposed_involvement", sa.Text(), nullable=True))
    if "coverage" not in columns:
        op.add_column("memberships", sa.Column("coverage", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("memberships", "coverage")
    op.drop_column("memberships", "proposed_involvement")
    op.drop_column("memberships", "involvement")
