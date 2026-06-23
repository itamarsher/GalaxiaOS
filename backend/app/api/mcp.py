"""Per-company MCP server management — connect founder-supplied tool servers.

Adding a server immediately probes it (``tools/list``) so a bad URL or token is
reported up front. Secrets are never returned; only whether auth is configured.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.deps import CompanyDep, DbDep
from app.models import McpServer
from app.schemas import McpServerCreateRequest, McpServerOut
from app.services import mcp as mcp_svc

router = APIRouter(prefix="/companies/{company_id}/mcp/servers", tags=["mcp"])


def _to_out(server: McpServer) -> McpServerOut:
    tools = server.tools_cache or []
    return McpServerOut(
        id=server.id,
        name=server.name,
        label=server.label,
        url=server.url,
        transport=server.transport,
        enabled=server.enabled,
        has_auth=server.encrypted_auth is not None,
        tool_count=len(tools),
        tools=[t.get("name", "") for t in tools if isinstance(t, dict)],
        last_error=server.last_error,
    )


@router.get("", response_model=list[McpServerOut])
async def list_servers(company: CompanyDep, db: DbDep):
    return [_to_out(s) for s in await mcp_svc.list_servers(db, company_id=company.id)]


@router.post("", response_model=McpServerOut, status_code=status.HTTP_201_CREATED)
async def add_server(company: CompanyDep, body: McpServerCreateRequest, db: DbDep):
    server = await mcp_svc.add_server(
        db,
        company_id=company.id,
        name=body.name,
        label=body.label or body.name,
        url=body.url.strip(),
        transport=body.transport,
        auth_token=(body.auth_token or None),
    )
    # Probe immediately so the founder sees whether it works (and which tools it has).
    await mcp_svc.refresh_tools(db, server=server)
    await db.commit()
    return _to_out(server)


@router.post("/{server_id}/refresh", response_model=McpServerOut)
async def refresh_server(company: CompanyDep, server_id: uuid.UUID, db: DbDep):
    servers = {s.id: s for s in await mcp_svc.list_servers(db, company_id=company.id)}
    server = servers.get(server_id)
    if server is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found")
    await mcp_svc.refresh_tools(db, server=server)
    await db.commit()
    return _to_out(server)


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_server(company: CompanyDep, server_id: uuid.UUID, db: DbDep):
    removed = await mcp_svc.remove_server(db, company_id=company.id, server_id=server_id)
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found")
    await db.commit()
