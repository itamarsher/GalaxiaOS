"""Data-segmentation labels on stored files.

Adds a nullable ``labels`` JSONB column to ``company_files`` holding the
``DataLabel`` keys that classify a stored file. Defaulted from the file's category
at archive time; the data policy gates which non-privileged principals may be shown
it (RFC 0001). Empty/NULL = general (accessible to everyone).

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this column on a fresh DB, so add it only if absent.

Revision ID: 0033_company_file_labels
Revises: 0032_data_segmentation
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0033_company_file_labels"
down_revision = "0032_data_segmentation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("company_files")}
    if "labels" not in columns:
        op.add_column("company_files", sa.Column("labels", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("company_files", "labels")
