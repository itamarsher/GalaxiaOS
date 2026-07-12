"""Real user registration (Google SSO + account-wide Drive) and the platform flag.

Two related changes replace the old fixed-founder Galaxia bootstrap hack:

- ``users`` gains the Google SSO identity (``google_sub``, ``name``), an
  account-wide (per-user, not per-company) Google Drive refresh-token bundle
  (envelope-encrypted, same shape as ``api_keys``), and ``hashed_password``
  becomes nullable (SSO accounts have no local password).
- ``companies`` gains ``is_platform`` — the single dogfooding company that runs
  GalaxiaOS on itself. A partial-unique index enforces at most one, and the
  promoter/render/cron gates key off it instead of a hard-coded founder id.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds these on a fresh DB, so add only what's absent.

Revision ID: 0026_user_sso_platform_company
Revises: 0025_mission_language
Create Date: 2026-07-12

(Revision id kept ≤32 chars — the length of ``alembic_version.version_num``.)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_user_sso_platform_company"
down_revision = "0025_mission_language"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    user_cols = {c["name"] for c in insp.get_columns("users")}
    if "google_sub" not in user_cols:
        op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
        op.create_index(
            "ix_users_google_sub", "users", ["google_sub"], unique=True
        )
    if "name" not in user_cols:
        op.add_column("users", sa.Column("name", sa.String(length=255), nullable=True))
    for col in ("gdrive_refresh_ct", "gdrive_refresh_dek", "gdrive_refresh_nonce"):
        if col not in user_cols:
            op.add_column("users", sa.Column(col, sa.LargeBinary(), nullable=True))
    if "gdrive_root_folder_id" not in user_cols:
        op.add_column(
            "users", sa.Column("gdrive_root_folder_id", sa.String(length=255), nullable=True)
        )
    # SSO accounts have no local password — relax the NOT NULL if the baseline set it.
    password_col = next(
        (c for c in insp.get_columns("users") if c["name"] == "hashed_password"), None
    )
    if password_col is not None and not password_col["nullable"]:
        op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=True)

    company_cols = {c["name"] for c in insp.get_columns("companies")}
    if "is_platform" not in company_cols:
        op.add_column(
            "companies",
            sa.Column("is_platform", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    # At most one platform company. A partial unique index over the ``true`` rows
    # lets every other company keep ``false`` while making a second platform
    # company a hard error.
    existing_indexes = {ix["name"] for ix in insp.get_indexes("companies")}
    if "uq_one_platform_company" not in existing_indexes:
        op.create_index(
            "uq_one_platform_company",
            "companies",
            ["is_platform"],
            unique=True,
            postgresql_where=sa.text("is_platform"),
        )


def downgrade() -> None:
    op.drop_index("uq_one_platform_company", table_name="companies")
    op.drop_column("companies", "is_platform")
    op.drop_index("ix_users_google_sub", table_name="users")
    for col in (
        "gdrive_root_folder_id",
        "gdrive_refresh_nonce",
        "gdrive_refresh_dek",
        "gdrive_refresh_ct",
        "name",
        "google_sub",
    ):
        op.drop_column("users", col)
