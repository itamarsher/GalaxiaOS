"""The Business-Function MCP endpoint — the pull transport (RFC 0001).

Exposes the worker-agnostic surface (``business_function``) to an external agent
runtime over MCP (JSON-RPC 2.0 / streamable-HTTP), so an OpenClaw / Claude Code
agent can *connect in*, fetch its mandate, claim initiatives on its own cadence,
and report results — the pull posture that complements the push ``OpenClawWorker``.

Two routers:

- ``mint_router`` — a **founder** action (``CompanyDep``): issue a connection token
  for one function so the founder can configure their external agent.
- ``router`` — the **MCP server** itself. It authenticates with the per-function
  connection token (a static ``Authorization: Bearer`` header, which OpenClaw
  supports for a remote MCP server) and scopes every call to that token's
  ``(company, function)``. It implements the minimal MCP method set the repo's own
  client speaks: ``initialize`` → ``notifications/initialized`` → ``tools/list`` /
  ``tools/call``.

The endpoint is inert until ``ABOS_FUNCTION_CONNECTION_SECRET`` is set (see
``function_token``): with no secret, every token fails verification and connections
are rejected — the pull transport is strictly opt-in.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.config import settings
from app.db import set_tenant
from app.deps import CompanyDep, CurrentUser, DbDep
from app.models import Agent
from app.services import business_function, function_token
from app.services import involvement as involvement_svc

# Mirror the protocol version the repo's MCP client advertises.
_PROTOCOL_VERSION = "2025-06-18"
_SERVER_INFO = {"name": "abos-business-function", "version": "0.1.0"}

# The tools the surface exposes to a connected worker.
_TOOL_SPECS = [
    {
        "name": "get_mandate",
        "description": "Your function's mandate: mission, objectives, budget envelope, "
        "constraints, and current metrics.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_next_initiative",
        "description": "The next initiative offered to your function, or null if idle.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "claim_initiative",
        "description": "Atomically claim an offered initiative so it's yours to work on.",
        "inputSchema": {
            "type": "object",
            "properties": {"initiative_id": {"type": "string"}},
            "required": ["initiative_id"],
        },
    },
    {
        "name": "report_result",
        "description": "Report the outcome of an initiative (done | failed | blocked | "
        "needs_decision) with a one-line summary.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "initiative_id": {"type": "string"},
                "outcome": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["initiative_id", "outcome"],
        },
    },
    {
        "name": "record_metric",
        "description": "Record a real business metric you observed or produced (e.g. "
        "revenue, signups). Persists to the company's metrics so it informs the "
        "mandate and reports — never invent one.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "number"},
                "unit": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["name", "value"],
        },
    },
    {
        "name": "write_memory",
        "description": "Write a durable learning/result/decision into Company Memory so "
        "it's recalled in future planning. type is one of "
        "decision|experiment|result|learning|strategy_shift (default learning).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "content": {"type": "string"},
                "type": {"type": "string"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "request_budget",
        "description": "Ask whether you may spend an amount (cents). A spend within the "
        "founder's remaining budget clears immediately ({cleared:true}) — proceed. Over "
        "budget escalates to the founder and parks this initiative until they decide; "
        "pass initiative_id so the parked initiative is the one you're working.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount_cents": {"type": "integer"},
                "reason": {"type": "string"},
                "initiative_id": {"type": "string"},
            },
            "required": ["amount_cents"],
        },
    },
]


# ── founder: mint a connection token for a function ────────────────────────────
mint_router = APIRouter(prefix="/companies/{company_id}", tags=["business-function"])


@mint_router.post("/functions/{agent_id}/connection")
async def mint_connection(
    company: CompanyDep, agent_id: uuid.UUID, db: DbDep, user: CurrentUser
):
    """Issue a connection token an external agent uses to staff this function.

    Founder-only: a connection token lets an external runtime pull this function's
    mandate and claim its initiatives, so minting one is the founder's call."""
    if not await involvement_svc.is_founder(db, company_id=company.id, user_id=user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the founder can connect an external agent")
    agent = await db.get(Agent, agent_id)
    if agent is None or agent.company_id != company.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "function not found")
    try:
        token = function_token.mint(company_id=company.id, agent_id=agent.id)
    except function_token.TokensDisabled as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    base = settings.public_api_base_url.rstrip("/")
    return {
        "function": agent.role.value,
        "token": token,
        "mcp_url": f"{base}/connect/business-function" if base else "/connect/business-function",
    }


# ── the MCP server ─────────────────────────────────────────────────────────────
router = APIRouter(tags=["business-function"])


def _bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth[:7].lower() == "bearer " else ""


def _ok(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _content(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


@router.post("/connect/business-function")
async def business_function_mcp(request: Request, db: DbDep):
    ident = function_token.verify(_bearer(request))
    if ident is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid function connection token")
    company_id, agent_id = ident
    await set_tenant(db, company_id)

    try:
        message = await request.json()
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid JSON-RPC body") from None
    if not isinstance(message, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid JSON-RPC body")

    method = message.get("method")
    mid = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        return _ok(mid, {
            "protocolVersion": _PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": _SERVER_INFO,
        })
    if method == "notifications/initialized":
        return Response(status_code=status.HTTP_202_ACCEPTED)
    if method == "tools/list":
        return _ok(mid, {"tools": _TOOL_SPECS})
    if method == "tools/call":
        return await _call_tool(db, company_id, agent_id, mid, params)
    return _error(mid, -32601, f"method not found: {method}")


async def _call_tool(db, company_id, agent_id, mid, params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    try:
        if name == "get_mandate":
            # A connection token holder is an external worker; segment its mandate.
            mandate = await business_function.get_mandate(
                db, company_id=company_id, agent_id=agent_id, redact_for_access=True
            )
            return _ok(mid, _content(mandate.model_dump(mode="json")))

        if name == "get_next_initiative":
            initiative = await business_function.get_next_initiative(
                db, company_id=company_id, agent_id=agent_id
            )
            return _ok(mid, _content(
                {"initiative": initiative.model_dump(mode="json") if initiative else None}
            ))

        if name == "claim_initiative":
            claimed = await business_function.claim_initiative(
                db, company_id=company_id, agent_id=agent_id,
                task_id=uuid.UUID(str(args["initiative_id"])),
            )
            await db.commit()
            return _ok(mid, _content(
                {"claimed": claimed is not None,
                 "initiative": claimed.model_dump(mode="json") if claimed else None}
            ))

        if name == "report_result":
            cost = await business_function.report_result(
                db, company_id=company_id,
                task_id=uuid.UUID(str(args["initiative_id"])),
                outcome=str(args["outcome"]),
                output={"summary": str(args.get("summary") or "")},
                agent_id=agent_id,  # a token scopes reports to its own function
            )
            await db.commit()
            return _ok(mid, _content({"ok": True, "cost_cents": cost}))

        if name == "record_metric":
            from app.models.enums import MetricSource
            from app.services import metrics as metrics_svc

            signal = await metrics_svc.record_signal(
                db, company_id=company_id, name=str(args["name"]),
                value=float(args["value"]),
                unit=(str(args["unit"]) if args.get("unit") else None),
                source=MetricSource.agent,
                note=(str(args["note"]) if args.get("note") else None),
            )
            await db.commit()
            return _ok(mid, _content({"ok": True, "metric_id": str(signal.id)}))

        if name == "write_memory":
            from app.models.enums import MemoryType
            from app.services import memory as memory_svc

            try:
                mtype = MemoryType(str(args.get("type") or "learning"))
            except ValueError:
                mtype = MemoryType.learning
            entry = await memory_svc.write(
                db, company_id=company_id, type=mtype,
                title=str(args["title"]), content=str(args["content"]),
            )
            await db.commit()
            return _ok(mid, _content({"ok": True, "memory_id": str(entry.id)}))

        if name == "request_budget":
            iid = args.get("initiative_id")
            result = await business_function.request_budget(
                db, company_id=company_id, agent_id=agent_id,
                amount_cents=int(args["amount_cents"]),
                reason=str(args.get("reason") or ""),
                initiative_id=uuid.UUID(str(iid)) if iid else None,
            )
            await db.commit()
            return _ok(mid, _content(result))

        return _error(mid, -32602, f"unknown tool: {name}")
    except (KeyError, ValueError) as exc:
        # A bad argument is a tool error, not a transport failure: report it as an
        # MCP error-content result so the agent can correct itself.
        return _ok(mid, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
