"""Data segmentation: label taxonomy + per-principal access policy.

Adds the ``data_labels`` table (the company's founder-editable data-classification
taxonomy) and an ``access_labels`` JSONB column on both ``agents`` and
``memberships`` (the DataLabel keys each non-privileged principal may be given).
Before data is handed to any principal that is not the founder or the CEO agent,
the data policy enforces that its labels are all permitted (RFC 0001).

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds these on a fresh DB, so create/add only if absent.

Revision ID: 0032_data_segmentation
Revises: 0031_membership_involvement
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0032_data_segmentation"
down_revision = "0031_membership_involvement"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if "data_labels" not in insp.get_table_names():
        op.create_table(
            "data_labels",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("company_id", sa.Uuid(), sa.ForeignKey("companies.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("key", sa.String(length=60), nullable=False, index=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                      nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                      nullable=False),
            sa.UniqueConstraint("company_id", "key", name="uq_data_label_company_key"),
        )

    for table in ("agents", "memberships"):
        columns = {c["name"] for c in insp.get_columns(table)}
        if "access_labels" not in columns:
            op.add_column(table, sa.Column("access_labels", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("memberships", "access_labels")
    op.drop_column("agents", "access_labels")
    op.drop_table("data_labels")
