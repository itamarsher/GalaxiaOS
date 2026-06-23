"""Per-company MCP server registry + tool exposure for the agent loop.

Founders connect their own MCP servers; this resolves them into ToolSpecs the
native loop can offer the model, and routes the model's calls back to the right
server. Tool names are namespaced ``mcp__{server}__{tool}`` so they can never
collide with built-in tools and so the loop can tell at a glance that a call is
external (it is then screened by governance as data egress).

Secrets (the optional bearer token) are envelope-encrypted on the row, mirroring
:mod:`app.services.apikeys`; the plaintext is decrypted only transiently here.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.crypto import envelope
from app.integrations.mcp_client import McpError, McpHttpClient
from app.models import McpServer
from app.providers.base import ToolSpec

__all__ = [
    "McpError",
    "list_servers",
    "add_server",
    "remove_server",
    "refresh_tools",
    "tool_specs_for_company",
    "call_tool",
    "tool_prefix",
]

_NAME_RE = re.compile(r"[^a-z0-9_]+")


def normalize_name(name: str) -> str:
    """Slugify a server name into the ``[a-z0-9_]`` charset used in tool prefixes."""
    slug = _NAME_RE.sub("_", (name or "").strip().lower()).strip("_")
    return slug or "server"


def tool_prefix(server_name: str) -> str:
    return f"mcp__{server_name}__"


def _auth_token(server: McpServer) -> str | None:
    if not (server.encrypted_auth and server.encrypted_data_key and server.nonce):
        return None
    return envelope.open_secret(
        envelope.SealedSecret(
            ciphertext=server.encrypted_auth,
            wrapped_data_key=server.encrypted_data_key,
            nonce=server.nonce,
        )
    )


def _client(server: McpServer) -> McpHttpClient:
    return McpHttpClient(server.url, auth_token=_auth_token(server))


async def list_servers(db: AsyncSession, *, company_id: uuid.UUID) -> list[McpServer]:
    rows = await db.scalars(
        select(McpServer).where(McpServer.company_id == company_id).order_by(McpServer.created_at)
    )
    return list(rows)


async def add_server(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    name: str,
    label: str,
    url: str,
    transport: str = "http",
    auth_token: str | None = None,
) -> McpServer:
    """Register a server (replacing any existing one with the same slug)."""
    slug = normalize_name(name)
    existing = await db.scalar(
        select(McpServer).where(McpServer.company_id == company_id, McpServer.name == slug)
    )
    server = existing or McpServer(company_id=company_id, name=slug)
    server.label = label or name or slug
    server.url = url
    server.transport = transport or "http"
    if auth_token:
        sealed = envelope.seal(auth_token)
        server.encrypted_auth = sealed.ciphertext
        server.encrypted_data_key = sealed.wrapped_data_key
        server.nonce = sealed.nonce
    server.enabled = True
    if existing is None:
        db.add(server)
    await db.flush()
    return server


async def remove_server(db: AsyncSession, *, company_id: uuid.UUID, server_id: uuid.UUID) -> bool:
    server = await db.scalar(
        select(McpServer).where(McpServer.id == server_id, McpServer.company_id == company_id)
    )
    if server is None:
        return False
    await db.delete(server)
    await db.flush()
    return True


async def refresh_tools(db: AsyncSession, *, server: McpServer) -> McpServer:
    """List the server's tools and cache them on the row; record any error.

    Never raises: a failed refresh is recorded in ``last_error`` and leaves the
    previous cache intact, so a transient outage doesn't wipe a server's tools.
    """
    try:
        tools = await _client(server).list_tools()
    except McpError as exc:
        server.last_error = str(exc)[:1000]
        await db.flush()
        return server
    server.tools_cache = tools
    server.last_error = None
    await db.flush()
    return server


async def tool_specs_for_company(
    db: AsyncSession, *, company_id: uuid.UUID
) -> tuple[list[ToolSpec], dict[str, dict]]:
    """Build (ToolSpecs, routing) for every enabled server's cached tools.

    ``routing`` maps each namespaced tool name to ``{server_id, remote_tool}`` so
    the loop can dispatch a model's call back to the originating server.
    """
    if not settings.mcp_enabled:
        return [], {}
    specs: list[ToolSpec] = []
    routing: dict[str, dict] = {}
    for server in await list_servers(db, company_id=company_id):
        if not server.enabled or not server.tools_cache:
            continue
        prefix = tool_prefix(server.name)
        for tool in server.tools_cache:
            remote = tool.get("name")
            if not remote:
                continue
            full = f"{prefix}{remote}"
            specs.append(
                ToolSpec(
                    name=full,
                    description=f"[{server.label}] {tool.get('description', '')}".strip(),
                    input_schema=tool.get("input_schema") or {"type": "object", "properties": {}},
                )
            )
            routing[full] = {"server_id": server.id, "remote_tool": remote}
    return specs, routing


async def call_tool(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    server_id: uuid.UUID,
    remote_tool: str,
    arguments: dict,
) -> str:
    server = await db.scalar(
        select(McpServer).where(McpServer.id == server_id, McpServer.company_id == company_id)
    )
    if server is None or not server.enabled:
        raise McpError("MCP server is no longer connected")
    return await _client(server).call_tool(remote_tool, arguments or {})
