"""Connected MCP (Model Context Protocol) servers — founder-pluggable tools.

A founder can register their own MCP servers (their CRM, analytics, internal APIs)
so agents gain real tools with no ABOS code change. The optional auth token is a
secret, so it is stored envelope-encrypted (same scheme as :class:`ApiKey`); the
non-secret URL/transport ride in plain columns. ``tools_cache`` holds the tool
specs discovered on the last successful refresh so the agent loop doesn't have to
hit the server on every run.
"""

from __future__ import annotations

from sqlalchemy import Boolean, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PKMixin, TenantMixin, TimestampMixin


class McpServer(Base, PKMixin, TenantMixin, TimestampMixin):
    __tablename__ = "mcp_servers"

    # Stable slug, unique per company; used to namespace tool names as
    # ``mcp__{name}__{tool}`` so they never collide with built-in tools.
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    transport: Mapped[str] = mapped_column(String(20), default="http", nullable=False)

    # Optional bearer token, envelope-encrypted (all three nullable when no auth).
    encrypted_auth: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    encrypted_data_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Tool specs ({name, description, input_schema}) from the last successful list.
    tools_cache: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
