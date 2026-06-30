"""Internal feature-request backlog: deduped demand ledger + per-voter attribution.

Adds two tables backing :mod:`app.models.feature_request`:

- ``feature_requests`` — one deduplicated capability/bug ask with a running vote
  tally and (once filed) the promoted tracker issue. Deliberately **global**: it
  aggregates demand across every tenant company, so it carries no ``company_id``
  boundary and gets no RLS policy.
- ``feature_request_votes`` — one row per (request, company, user) recording who
  asked. Tenant-scoped like every other ``company_id`` table, so RLS is enabled
  (same permissive-until-GUC policy shape as ``0014_chat``); the unscoped promoter
  session — which never sets ``app.current_company`` — still sees all votes.

Additive and idempotent: the 0001 baseline ``create_all`` builds these on a fresh
DB, so create only if absent.

Revision ID: 0019_feature_requests
Revises: 0018_task_chat_seen_at
Create Date: 2026-06-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0019_feature_requests"
down_revision = "0018_task_chat_seen_at"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"

_TIMESTAMPS = (
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
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

    if not insp.has_table("feature_requests"):
        op.create_table(
            "feature_requests",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("dedup_key", sa.String(length=560), nullable=False),
            sa.Column("details", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
            sa.Column("vote_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("github_issue_number", sa.Integer(), nullable=True),
            sa.Column("github_issue_url", sa.String(length=1000), nullable=True),
            *_TIMESTAMPS,
            sa.UniqueConstraint("dedup_key", name="uq_feature_request_dedup_key"),
        )
        op.create_index("ix_feature_requests_kind", "feature_requests", ["kind"])
        op.create_index("ix_feature_requests_status", "feature_requests", ["status"])

    if not insp.has_table("feature_request_votes"):
        op.create_table(
            "feature_request_votes",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            sa.Column(
                "feature_request_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("feature_requests.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "company_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "user_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("users.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("details", sa.Text(), nullable=True),
            *_TIMESTAMPS,
            sa.UniqueConstraint(
                "feature_request_id", "company_id", "user_id", name="uq_feature_request_vote"
            ),
        )
        op.create_index(
            "ix_feature_request_votes_request_id", "feature_request_votes", ["feature_request_id"]
        )
        op.create_index(
            "ix_feature_request_votes_company_id", "feature_request_votes", ["company_id"]
        )
        op.create_index("ix_feature_request_votes_user_id", "feature_request_votes", ["user_id"])

    # Only the votes table carries company_id → tenant-scoped under RLS. The parent
    # backlog is global by design and gets no policy.
    _enable_rls("feature_request_votes")


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON feature_request_votes")
    op.drop_table("feature_request_votes")
    op.drop_table("feature_requests")
