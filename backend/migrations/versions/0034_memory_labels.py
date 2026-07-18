"""Data-segmentation labels on memory entries.

Adds a nullable ``labels`` JSONB column to ``memory_entries`` holding the
``DataLabel`` keys that classify a recalled memory. Sensitive sources (financial,
legal, filed documents) tag their writes; the recall path withholds an entry from
any agent not cleared for its labels before it is injected into the prompt
(RFC 0001). Empty/NULL = general (recalled for everyone).

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this column on a fresh DB, so add it only if absent.

Revision ID: 0034_memory_labels
Revises: 0033_company_file_labels
Create Date: 2026-07-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0034_memory_labels"
down_revision = "0033_company_file_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("memory_entries")}
    if "labels" not in columns:
        op.add_column("memory_entries", sa.Column("labels", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("memory_entries", "labels")
