"""Managed-mode platform billing: per-founder allowance + platform-spend ledger.

Adds two tables backing :mod:`app.models.billing` for the hosted "no keys
needed" tier:

- ``platform_billing_accounts`` — one row per founder (``user_id``) holding their
  managed tier and cumulative platform-funded spend.
- ``platform_charges`` — an append-only ledger of every platform-funded charge
  (audit trail + paid-managed billing feed).

Both are keyed by ``user_id`` and cross the tenant boundary by design (a
founder's free tier is pooled across all their companies), so — like ``users``
and the shared ``feature_requests`` backlog — they carry no ``company_id``
boundary and get **no** RLS policy.

Additive and idempotent: the 0001 baseline ``create_all`` builds these on a
fresh DB, so create only if absent.

Revision ID: 0024_platform_billing
Revises: 0023_task_objective_id
Create Date: 2026-07-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0024_platform_billing"
down_revision = "0023_task_objective_id"
branch_labels = None
depends_on = None

_TIMESTAMPS = (
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("platform_billing_accounts"):
        op.create_table(
            "platform_billing_accounts",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tier", sa.String(length=20), nullable=False, server_default="free"),
            sa.Column(
                "platform_spent_cents", sa.Integer(), nullable=False, server_default="0"
            ),
            sa.Column("stripe_customer_id", sa.String(length=80), nullable=True),
            sa.Column("stripe_subscription_item_id", sa.String(length=80), nullable=True),
            *_TIMESTAMPS,
            sa.UniqueConstraint("user_id", name="uq_platform_billing_account_user"),
        )
        op.create_index(
            "ix_platform_billing_accounts_user_id",
            "platform_billing_accounts",
            ["user_id"],
        )

    if not insp.has_table("platform_charges"):
        op.create_table(
            "platform_charges",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "company_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("cents", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=40), nullable=False),
            sa.Column("billed", sa.Boolean(), nullable=False, server_default=sa.false()),
            *_TIMESTAMPS,
        )
        op.create_index("ix_platform_charges_user_id", "platform_charges", ["user_id"])
        op.create_index("ix_platform_charges_company_id", "platform_charges", ["company_id"])


def downgrade() -> None:
    op.drop_table("platform_charges")
    op.drop_table("platform_billing_accounts")
