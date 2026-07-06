"""Per-company operating playbook (global agent system prompt).

Adds a nullable ``playbook`` column to ``companies``: the global system prompt
injected into every agent's launch prompt (best practices of ABOS + this company's
directives). The CEO edits it as emerging directives arise; when unset, the
platform default (``app.runtime.prompts.DEFAULT_COMPANY_PLAYBOOK``) applies.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds this column on a fresh DB, so add it only if absent.

Revision ID: 0010_company_playbook
Revises: 0009_company_files
Create Date: 2026-06-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_company_playbook"
down_revision = "0009_company_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    columns = {c["name"] for c in insp.get_columns("companies")}
    if "playbook" not in columns:
        op.add_column("companies", sa.Column("playbook", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("companies", "playbook")
