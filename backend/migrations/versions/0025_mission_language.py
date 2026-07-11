"""Detected founder language on the mission.

Adds a nullable ``language`` column to ``missions`` holding the BCP-47 tag of the
language the founder's mission is written in. It is detected once during
onboarding (the mission → plan stage, which reads the raw mission) and reused by
every later generation stage — org design, investor review, refine — so all the
company's generated text lands in one language deterministically instead of each
stage re-detecting from derived, JSON-wrapped text and drifting.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this column on a fresh DB, so add it only if absent.

Revision ID: 0025_mission_language
Revises: 0024_platform_billing
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_mission_language"
down_revision = "0024_platform_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("missions")}
    if "language" not in columns:
        op.add_column("missions", sa.Column("language", sa.String(length=20), nullable=True))


def downgrade() -> None:
    op.drop_column("missions", "language")
