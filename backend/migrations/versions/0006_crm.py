"""Self-coded CRM tables — contacts, deals, activities.

Adds three tenant tables backing the real CRM the sales/growth agents read and
write (replacing the old fabricated stubs):
- ``crm_contacts`` — people / accounts.
- ``crm_deals`` — pipeline opportunities (FK -> crm_contacts, SET NULL).
- ``crm_activities`` — logged interactions / planned touchpoints (FK -> contacts & deals).

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds these on a fresh DB, so create only if absent.
RLS is enabled to match every other tenant table (permissive-until-adopted,
same policy shape as ``0002_row_level_security``).

Revision ID: 0006_crm
Revises: 0005_decision_chat
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0006_crm"
down_revision = "0005_decision_chat"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
_NEW_TABLES = ("crm_contacts", "crm_deals", "crm_activities")

_TIMESTAMPS = (
    sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    ),
    sa.Column(
        "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    ),
)


def _company_fk() -> sa.Column:
    return sa.Column(
        "company_id",
        PGUUID(as_uuid=True),
        sa.ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    op.execute(
        f"CREATE POLICY {POLICY} ON {table} "
        "USING ("
        f"current_setting('{GUC}', true) IS NULL "
        f"OR current_setting('{GUC}', true) = '' "
        f"OR company_id = current_setting('{GUC}', true)::uuid"
        ") WITH CHECK ("
        f"current_setting('{GUC}', true) IS NULL "
        f"OR current_setting('{GUC}', true) = '' "
        f"OR company_id = current_setting('{GUC}', true)::uuid"
        ")"
    )


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not insp.has_table("crm_contacts"):
        op.create_table(
            "crm_contacts",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("email", sa.String(length=320), nullable=True),
            sa.Column("phone", sa.String(length=50), nullable=True),
            sa.Column("company_name", sa.String(length=255), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="lead"),
            sa.Column("source", sa.String(length=255), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("structured", JSONB(), nullable=True),
            *_TIMESTAMPS,
        )
        op.create_index("ix_crm_contacts_company_id", "crm_contacts", ["company_id"])
        op.create_index("ix_crm_contacts_email", "crm_contacts", ["email"])
        op.create_index("ix_crm_contacts_status", "crm_contacts", ["status"])

    if not insp.has_table("crm_deals"):
        op.create_table(
            "crm_deals",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column(
                "contact_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("stage", sa.String(length=20), nullable=False, server_default="new"),
            sa.Column("amount_cents", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            *_TIMESTAMPS,
        )
        op.create_index("ix_crm_deals_company_id", "crm_deals", ["company_id"])
        op.create_index("ix_crm_deals_contact_id", "crm_deals", ["contact_id"])
        op.create_index("ix_crm_deals_stage", "crm_deals", ["stage"])

    if not insp.has_table("crm_activities"):
        op.create_table(
            "crm_activities",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="note"),
            sa.Column("subject", sa.String(length=500), nullable=True),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column(
                "contact_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("crm_contacts.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "deal_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("crm_deals.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
            *_TIMESTAMPS,
        )
        op.create_index("ix_crm_activities_company_id", "crm_activities", ["company_id"])
        op.create_index("ix_crm_activities_contact_id", "crm_activities", ["contact_id"])
        op.create_index("ix_crm_activities_deal_id", "crm_activities", ["deal_id"])
        op.create_index("ix_crm_activities_kind", "crm_activities", ["kind"])

    for table in _NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS crm_activities")
    op.execute("DROP TABLE IF EXISTS crm_deals")
    op.execute("DROP TABLE IF EXISTS crm_contacts")
