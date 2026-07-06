"""Clear existing CEO per-agent budget caps.

The CEO owns the whole company budget and its reserve pool, so it is never
given a per-agent ``monthly_budget_cents`` slice — it is gated only by the
global company budget in ``budget.reserve()``. New companies already onboard
this way (the CEO is excluded from the weighted split), but companies
provisioned before that change still carry a CEO cap. Null those out so the
CEO is limited only by the global budget everywhere.

Data-only and idempotent: it just sets ``monthly_budget_cents = NULL`` for
CEO rows that still have a cap.

Revision ID: 0022_clear_ceo_budget_cap
Revises: 0021_task_reliability_reviewed
Create Date: 2026-07-06
"""

from __future__ import annotations

from alembic import op

revision = "0022_clear_ceo_budget_cap"
down_revision = "0021_task_reliability_reviewed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE agents SET monthly_budget_cents = NULL "
        "WHERE role = 'ceo' AND monthly_budget_cents IS NOT NULL"
    )


def downgrade() -> None:
    # Irreversible: the pre-migration per-agent CEO caps are not retained.
    pass
