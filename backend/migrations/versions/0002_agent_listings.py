"""Agent marketplace catalog: agent_listings (global) + seed listings.

Revision ID: 0002_agent_listings
Revises: 0002_row_level_security
Create Date: 2026-06-13
"""

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0002_agent_listings"
# Chained after the RLS migration so there is a single Alembic head.
down_revision = "0002_row_level_security"
branch_labels = None
depends_on = None


def upgrade() -> None:
    listings = op.create_table(
        "agent_listings",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
        sa.Column("trust", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("roi", sa.Float(), nullable=True),
        sa.Column("reliability", sa.Float(), nullable=True),
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

    op.bulk_insert(
        listings,
        [
            {
                "id": uuid.uuid4(),
                "name": "Apex Growth Hacker",
                "role": "growth",
                "description": "Performance marketing specialist: paid acquisition, funnel optimisation, and channel experiments.",
                "provider": "GrowthLabs",
                "price_cents": 1500,
                "trust": 0.88,
                "accuracy": 0.85,
                "roi": 0.82,
                "reliability": 0.90,
            },
            {
                "id": uuid.uuid4(),
                "name": "DeepDive Research Analyst",
                "role": "research",
                "description": "Market and competitive research agent producing sourced, structured briefs.",
                "provider": "InsightWorks",
                "price_cents": 1200,
                "trust": 0.83,
                "accuracy": 0.91,
                "roi": 0.70,
                "reliability": 0.86,
            },
            {
                "id": uuid.uuid4(),
                "name": "Forge Product Engineer",
                "role": "product",
                "description": "Builds and iterates on product specs, prototypes, and roadmaps.",
                "provider": "BuildCo",
                "price_cents": 2200,
                "trust": 0.80,
                "accuracy": 0.78,
                "roi": 0.75,
                "reliability": 0.82,
            },
            {
                "id": uuid.uuid4(),
                "name": "Ledger Finance Controller",
                "role": "finance",
                "description": "Tracks burn, models runway, and flags spend anomalies.",
                "provider": "FinOps Collective",
                "price_cents": 1800,
                "trust": 0.92,
                "accuracy": 0.94,
                "roi": 0.68,
                "reliability": 0.95,
            },
            {
                "id": uuid.uuid4(),
                "name": "Sentinel Compliance Officer",
                "role": "governance",
                "description": "Reviews actions against policy and surfaces governance risks.",
                "provider": "SafeGuard AI",
                "price_cents": 2000,
                "trust": 0.95,
                "accuracy": 0.96,
                "roi": 0.60,
                "reliability": 0.97,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("agent_listings")
