"""Team invites: a pending-membership table consumed on authentication.

Adds ``company_invites`` — a founder invites a teammate by email with pre-set
access labels; the row is consumed (a Membership created) when that email next
authenticates (RFC 0001, human binding). Idempotent: the 0001 baseline's
``create_all`` builds this table on a fresh DB, so create it only if absent.

Revision ID: 0035_company_invites
Revises: 0034_memory_labels
Create Date: 2026-07-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0035_company_invites"
down_revision = "0034_memory_labels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "company_invites" in insp.get_table_names():
        return
    op.create_table(
        "company_invites",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("company_id", PGUUID(as_uuid=True),
                  sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("email", sa.String(length=320), nullable=False, index=True),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="admin"),
        sa.Column("access_labels", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending", index=True),
        sa.Column("invited_by_user_id", PGUUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("accepted_user_id", PGUUID(as_uuid=True),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("company_invites")
