"""Outcome signals + investment reviews.

Adds two tenant tables:
- ``metric_signals`` — real-world business outcomes the agents read back.
- ``investment_reviews`` — the three onboarding investor verdicts.

Idempotent like the other additive migrations: the 0001 baseline's
``create_all`` already builds these on a fresh DB, so create only if absent.
RLS is enabled to match every other tenant table (permissive-until-adopted,
same policy shape as ``0002_row_level_security``).

Revision ID: 0003_metrics_investment
Revises: 0002_agent_listings
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0003_metrics_investment"
down_revision = "0002_agent_listings"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
_NEW_TABLES = ("metric_signals", "investment_reviews")


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

    if not insp.has_table("metric_signals"):
        op.create_table(
            "metric_signals",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column(
                "company_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("unit", sa.String(length=50), nullable=True),
            sa.Column("source", sa.String(length=20), nullable=False, server_default="founder"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("structured", JSONB(), nullable=True),
            sa.Column(
                "captured_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index("ix_metric_signals_company_id", "metric_signals", ["company_id"])
        op.create_index("ix_metric_signals_name", "metric_signals", ["name"])

    if not insp.has_table("investment_reviews"):
        op.create_table(
            "investment_reviews",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column(
                "company_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("persona", sa.String(length=30), nullable=False),
            sa.Column("stance", sa.String(length=20), nullable=False),
            sa.Column("conviction", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("headline", sa.String(length=500), nullable=False, server_default=""),
            sa.Column("thesis", sa.Text(), nullable=False, server_default=""),
            sa.Column("strengths", JSONB(), nullable=True),
            sa.Column("risks", JSONB(), nullable=True),
            sa.Column("conditions", JSONB(), nullable=True),
            sa.Column("model", sa.String(length=80), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_investment_reviews_company_id", "investment_reviews", ["company_id"]
        )
        op.create_index("ix_investment_reviews_persona", "investment_reviews", ["persona"])

    for table in _NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP TABLE IF EXISTS investment_reviews")
    op.execute("DROP TABLE IF EXISTS metric_signals")
