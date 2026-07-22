"""Drop the is_platform flag — the operator company is now explicit config.

The magic ``companies.is_platform`` flag (auto-set on the first company onboarded)
is replaced by ``ABOS_PLATFORM_COMPANY_ID`` pointing at a normal company. Drop the
partial-unique index ``uq_one_platform_company`` and the column, so the dogfooding
company is an ordinary tenant. Guarded (idempotent) so it's safe on any DB.

Revision ID: 0036_drop_platform_flag
Revises: 0035_company_invites
Create Date: 2026-07-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036_drop_platform_flag"
down_revision = "0035_company_invites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    indexes = {ix["name"] for ix in insp.get_indexes("companies")}
    if "uq_one_platform_company" in indexes:
        op.drop_index("uq_one_platform_company", table_name="companies")
    columns = {c["name"] for c in insp.get_columns("companies")}
    if "is_platform" in columns:
        op.drop_column("companies", "is_platform")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("companies")}
    if "is_platform" not in columns:
        op.add_column(
            "companies",
            sa.Column("is_platform", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    indexes = {ix["name"] for ix in insp.get_indexes("companies")}
    if "uq_one_platform_company" not in indexes:
        op.create_index(
            "uq_one_platform_company",
            "companies",
            ["is_platform"],
            unique=True,
            postgresql_where=sa.text("is_platform"),
        )
