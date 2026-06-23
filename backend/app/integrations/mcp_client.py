"""A small MCP (Model Context Protocol) client over Streamable HTTP / JSON-RPC.

Speaks just enough of the protocol for the two operations the agent loop needs:
``tools/list`` (discover a server's tools) and ``tools/call`` (invoke one). The
handshake is ``initialize`` → ``notifications/initialized`` → the request; a
``Mcp-Session-Id`` header returned by the server is echoed back on subsequent
calls. Responses may come back as JSON or as an SSE stream, and both are handled.

Honest-by-design: every failure path raises :class:`McpError`, which the runtime
surfaces to the agent as a tool error. We never fabricate a result for an
unreachable or misbehaving server — consistent with the rest of the platform.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import settings

_PROTOCOL_VERSION = "2025-06-18"
_CLIENT_INFO = {"name": "abos", "version": "0.1.0"}


class McpError(Exception):
    """An MCP server call failed (unreachable, protocol error, or tool error)."""


def _parse_response(resp: httpx.Response) -> dict[str, Any]:
    """Return the JSON-RPC message from a response that is JSON or SSE."""
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        # Walk SSE ``data:`` lines and return the first object carrying a JSON-RPC
        # ``result``/``error`` (the response to our request).
        for line in resp.text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line[len("data:") :].strip()
            if not payload:
                continue
            try:
                msg = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and ("result" in msg or "error" in msg):
                return msg
        raise McpError("no JSON-RPC result found in SSE response")
    try:
        return resp.json()
    except json.JSONDecodeError as exc:
        raise McpError(f"non-JSON response from MCP server: {resp.text[:200]}") from exc


class McpHttpClient:
    def __init__(self, url: str, *, auth_token: str | None = None) -> None:
        self._url = url
        self._headers = {
            "Content-Type": "application/json",
            # Per the Streamable HTTP transport, accept both content types.
            "Accept": "application/json, text/event-stream",
        }
        if auth_token:
            self._headers["Authorization"] = f"Bearer {auth_token}"
        self._session_id: str | None = None

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: dict | None) -> dict:
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            resp = await client.post(self._url, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise McpError(f"could not reach MCP server: {exc}") from exc
        if resp.status_code >= 400:
            raise McpError(f"MCP server returned HTTP {resp.status_code}: {resp.text[:200]}")
        sid = resp.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        msg = _parse_response(resp)
        if "error" in msg:
            err = msg["error"]
            raise McpError(str(err.get("message", err)) if isinstance(err, dict) else str(err))
        return msg.get("result", {})

    async def _notify(self, client: httpx.AsyncClient, method: str) -> None:
        body = {"jsonrpc": "2.0", "method": method, "params": {}}
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        try:
            await client.post(self._url, json=body, headers=headers)
        except httpx.HTTPError:
            # Notifications are best-effort; the next request will surface a real error.
            pass

    async def _handshake(self, client: httpx.AsyncClient) -> None:
        await self._rpc(
            client,
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": _CLIENT_INFO,
            },
        )
        await self._notify(client, "notifications/initialized")

    async def list_tools(self) -> list[dict]:
        """Return the server's tools as ``[{name, description, input_schema}]``."""
        async with httpx.AsyncClient(timeout=settings.mcp_timeout_seconds) as client:
            await self._handshake(client)
            result = await self._rpc(client, "tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        out: list[dict] = []
        for tool in tools[: settings.mcp_max_tools_per_server]:
            if not isinstance(tool, dict) or "name" not in tool:
                continue
            out.append(
                {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("inputSchema") or {"type": "object", "properties": {}},
                }
            )
        return out

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Invoke a tool and return its textual result content."""
        async with httpx.AsyncClient(timeout=settings.mcp_timeout_seconds) as client:
            await self._handshake(client)
            result = await self._rpc(client, "tools/call", {"name": name, "arguments": arguments or {}})
        if not isinstance(result, dict):
            return str(result)
        if result.get("isError"):
            raise McpError(_render_content(result.get("content")) or "tool reported an error")
        return _render_content(result.get("content")) or json.dumps(result)[:4000]


def _render_content(content: Any) -> str:
    """Flatten MCP content blocks (text/json) into a single string."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content if isinstance(content, list) else [content]:
        if isinstance(block, dict):
            if block.get("type") == "text" and "text" in block:
                parts.append(str(block["text"]))
            elif "text" in block:
                parts.append(str(block["text"]))
            else:
                parts.append(json.dumps(block))
        else:
            parts.append(str(block))
    return "\n".join(p for p in parts if p)
