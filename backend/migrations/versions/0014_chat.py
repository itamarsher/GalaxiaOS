"""In-house chat: channels, participants, messages, and reply-waits.

Adds four tenant tables backing the fleet's collaboration layer (see
:mod:`app.models.chat`):

- ``chat_channels`` — named initiative channels and 1:1 direct threads.
- ``chat_participants`` — who is in each channel (``agent_id NULL`` = founder).
- ``chat_messages`` — the messages (``sender_agent_id NULL`` = founder).
- ``chat_waits`` — an agent's parked "wait for a reply" request, the chat analog
  of a parked founder decision.

Additive and idempotent like the other migrations: the 0001 baseline's
``create_all`` already builds these on a fresh DB, so create only if absent. RLS
is enabled on each to match every other tenant table (same policy shape as
``0011_external_messages`` / ``0013_mcp_and_artifacts``).

Revision ID: 0014_chat
Revises: 0013_mcp_and_artifacts
Create Date: 2026-06-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0014_chat"
down_revision = "0013_mcp_and_artifacts"
branch_labels = None
depends_on = None

GUC = "app.current_company"
POLICY = "tenant_isolation"
_NEW_TABLES = ("chat_channels", "chat_participants", "chat_messages", "chat_waits")

_TIMESTAMPS = (
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
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

    if not insp.has_table("chat_channels"):
        op.create_table(
            "chat_channels",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("purpose", sa.Text(), nullable=True),
            sa.Column("kind", sa.String(length=20), nullable=False, server_default="channel"),
            sa.Column(
                "created_by_agent_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
            *_TIMESTAMPS,
        )
        op.create_index("ix_chat_channels_company_id", "chat_channels", ["company_id"])

    if not insp.has_table("chat_participants"):
        op.create_table(
            "chat_participants",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column(
                "channel_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("chat_channels.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "agent_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="CASCADE"),
                nullable=True,
            ),
            *_TIMESTAMPS,
            sa.UniqueConstraint("channel_id", "agent_id", name="uq_chat_participant"),
        )
        op.create_index("ix_chat_participants_company_id", "chat_participants", ["company_id"])
        op.create_index("ix_chat_participants_channel_id", "chat_participants", ["channel_id"])

    if not insp.has_table("chat_messages"):
        op.create_table(
            "chat_messages",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column(
                "channel_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("chat_channels.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "sender_agent_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("body", sa.Text(), nullable=False),
            *_TIMESTAMPS,
        )
        op.create_index("ix_chat_messages_company_id", "chat_messages", ["company_id"])
        op.create_index("ix_chat_messages_channel_id", "chat_messages", ["channel_id"])

    if not insp.has_table("chat_waits"):
        op.create_table(
            "chat_waits",
            sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
            _company_fk(),
            sa.Column(
                "channel_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("chat_channels.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "task_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("tasks.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "agent_id",
                PGUUID(as_uuid=True),
                sa.ForeignKey("agents.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            *_TIMESTAMPS,
        )
        op.create_index("ix_chat_waits_company_id", "chat_waits", ["company_id"])
        op.create_index("ix_chat_waits_channel_id", "chat_waits", ["channel_id"])
        op.create_index("ix_chat_waits_task_id", "chat_waits", ["task_id"])
        op.create_index("ix_chat_waits_status", "chat_waits", ["status"])

    for table in _NEW_TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in _NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
    op.drop_table("chat_waits")
    op.drop_table("chat_messages")
    op.drop_table("chat_participants")
    op.drop_table("chat_channels")
