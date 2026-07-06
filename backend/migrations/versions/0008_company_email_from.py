"""Per-company sender ("From:") address.

Adds a nullable ``email_from`` column to ``companies`` so a founder can set the
address their agents send mail as (for Resend it must be on a domain verified in
their Resend account). When unset, the email sender falls back to the global
``ABOS_EMAIL_FROM``.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this column on a fresh DB, so add it only if absent.

Revision ID: 0008_company_email_from
Revises: 0007_sites
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_company_email_from"
down_revision = "0007_sites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("companies")}
    if "email_from" not in columns:
        op.add_column("companies", sa.Column("email_from", sa.String(length=320), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "email_from")
