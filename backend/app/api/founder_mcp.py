"""The Founder MCP — an agent-first control surface for a user's own AI operator.

Where the Business-Function MCP (``bf_mcp.py``) lets an external agent *operate*
one function slot of one company, the Founder MCP lets a user's AI act as the
**founder**: register/create a company, run onboarding (generate → refine →
launch), read a live snapshot, resolve the founder decisions that gate the work
(plans, hires, spend, external comms), run a cycle, and edit the playbook — all
over MCP, with no human UI.

The gates stay (a plan/hire/spend/comms decision is still raised for auditability);
the difference is that the *founder's AI* can resolve them via ``approve_decision``/
``reject_decision`` instead of a human clicking in the app.

Auth: a per-user founder connection token (``founder_token``), minted by the
already-authenticated user. Every company-scoped tool re-checks that the token's
user is the founder of the named company before touching it.
"""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import func, select

from app.config import settings
from app.db import set_tenant
from app.deps import CurrentUser, DbDep
from app.models import (
    Agent,
    Budget,
    Company,
    DecisionRequest,
    Membership,
    Objective,
    Task,
    User,
)
from app.models.enums import CompanyStatus, DecisionStatus, TaskStatus
from app.runtime.queue import enqueue_task
from app.services import founder_token, involvement, onboarding
from app.services import runs as runs_svc
from app.services.decisions import resolve_decision
from app.services.onboarding import OnboardingError

_PROTOCOL_VERSION = "2024-11-05"
_SERVER_INFO = {"name": "abos-founder", "version": "0.1.0"}

_ACTIVE_TASK_STATUSES = (
    TaskStatus.queued,
    TaskStatus.running,
    TaskStatus.waiting_approval,
    TaskStatus.auditing,
)

_TOOL_SPECS = [
    {
        "name": "list_companies",
        "description": "List every company you (the founder) own, with id, name, and status "
        "(draft/active). Use this to find a company_id for the other tools.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_company",
        "description": "Create a new company from a mission and a monthly budget. Returns its "
        "company_id in 'draft' status. Next call generate_org, then (optionally) refine_plan, "
        "then launch_company.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mission_text": {"type": "string", "description": "What the company should do."},
                "budget_cents": {"type": "integer", "description": "Monthly budget, in cents."},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "involvement": {
                    "type": "string",
                    "description": "Optional: how the founder wants to be involved (drives which "
                    "decisions auto-resolve vs. escalate).",
                },
            },
            "required": ["mission_text", "budget_cents"],
        },
    },
    {
        "name": "generate_org",
        "description": "Run onboarding generation for a draft company: the LLM designs the "
        "objectives, agent fleet, and budget split. Returns the generated plan preview.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}},
            "required": ["company_id"],
        },
    },
    {
        "name": "refine_plan",
        "description": "Conversationally revise a draft company's generated plan (objectives, "
        "fleet, budget) in natural language before launching. Returns the updated preview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "message": {"type": "string", "description": "What to change about the plan."},
            },
            "required": ["company_id", "message"],
        },
    },
    {
        "name": "launch_company",
        "description": "Launch a draft company: transitions it to 'active' and starts the CEO's "
        "first run. After this the company operates autonomously; use get_company_snapshot and "
        "the decision tools to steer it.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}},
            "required": ["company_id"],
        },
    },
    {
        "name": "get_company_snapshot",
        "description": "A live snapshot of a company: status, objectives, budget/spend, cycle "
        "state, live agents, active task count, and pending founder decisions. This is your main "
        "read to decide what (if anything) to steer.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}},
            "required": ["company_id"],
        },
    },
    {
        "name": "list_decisions",
        "description": "List the company's pending founder decisions (plan approvals, hires, "
        "over-budget spend, external comms). Each has an id, kind, and summary. Resolve them with "
        "approve_decision / reject_decision.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}},
            "required": ["company_id"],
        },
    },
    {
        "name": "approve_decision",
        "description": "Approve a pending founder decision so the blocked work proceeds. You are "
        "acting as the founder — approve only what you'd want the company to do.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "decision_id": {"type": "string"},
                "note": {"type": "string", "description": "Optional note delivered to the agent."},
            },
            "required": ["company_id", "decision_id"],
        },
    },
    {
        "name": "reject_decision",
        "description": "Reject a pending founder decision. The owning agent resumes and adapts. "
        "Include a note explaining why so it can course-correct.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "decision_id": {"type": "string"},
                "note": {
                    "type": "string",
                    "description": "Why you're rejecting (guides the agent).",
                },
            },
            "required": ["company_id", "decision_id"],
        },
    },
    {
        "name": "run_cycle",
        "description": "Kick off one business cycle on demand (the CEO reviews state and dispatches "
        "the next initiatives). No-ops if a cycle is already running.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}},
            "required": ["company_id"],
        },
    },
    {
        "name": "set_playbook",
        "description": "Replace the company's global operating playbook (the system prompt every "
        "agent runs under). An empty string reverts to the platform default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "playbook": {"type": "string"},
            },
            "required": ["company_id", "playbook"],
        },
    },
]


# ── mint a founder connection token (an authenticated-user action) ─────────────
mint_router = APIRouter(tags=["founder"])


@mint_router.post("/founder/connection")
async def mint_founder_connection(user: CurrentUser):
    """Issue a founder connection token so the user's AI can operate on their behalf.

    Powerful (full account power across the user's companies), so it's only mintable
    by the authenticated user for themselves."""
    try:
        token = founder_token.mint(user_id=user.id)
    except founder_token.TokensDisabled as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    base = settings.public_api_base_url.rstrip("/")
    return {
        "token": token,
        "mcp_url": f"{base}/connect/founder" if base else "/connect/founder",
    }


# ── the MCP server ─────────────────────────────────────────────────────────────
router = APIRouter(tags=["founder"])


def _bearer(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    return auth[7:].strip() if auth[:7].lower() == "bearer " else ""


def _ok(mid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _content(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


async def _founder_company(db, user_id: uuid.UUID, company_id_raw: object) -> Company:
    """Load a company the token's user founds, RLS-scope the session to it, or 404/403.

    Every company-scoped tool goes through here so the founder token can only touch
    companies the user actually owns — the token grants no cross-account reach.
    """
    try:
        company_id = uuid.UUID(str(company_id_raw))
    except (ValueError, TypeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid company_id") from None
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "company not found")
    if not await involvement.is_founder(db, company_id=company.id, user_id=user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not the founder of this company")
    await set_tenant(db, company.id)
    return company


@router.post("/connect/founder")
async def founder_mcp(request: Request, db: DbDep):
    user_id = founder_token.verify(_bearer(request))
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid founder connection token")

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
        return _ok(
            mid,
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": _SERVER_INFO,
            },
        )
    if method == "notifications/initialized":
        return Response(status_code=status.HTTP_202_ACCEPTED)
    if method == "tools/list":
        return _ok(mid, {"tools": _TOOL_SPECS})
    if method == "tools/call":
        return await _call_tool(db, user_id, mid, params)
    return _error(mid, -32601, f"method not found: {method}")


async def _snapshot(db, company: Company) -> dict:
    objectives = (
        await db.scalars(
            select(Objective).where(Objective.company_id == company.id).order_by(Objective.priority)
        )
    ).all()
    budget = await db.scalar(select(Budget).where(Budget.company_id == company.id))
    agents = (await db.scalars(select(Agent).where(Agent.company_id == company.id))).all()
    active_tasks = await db.scalar(
        select(func.count(Task.id)).where(
            Task.company_id == company.id, Task.status.in_(_ACTIVE_TASK_STATUSES)
        )
    )
    pending = (
        await db.scalars(
            select(DecisionRequest).where(
                DecisionRequest.company_id == company.id,
                DecisionRequest.status == DecisionStatus.pending,
            )
        )
    ).all()
    cycle = await runs_svc.cycle_status(db, company)
    return {
        "company": {"id": str(company.id), "name": company.name, "status": company.status.value},
        "objectives": [{"title": o.title, "status": o.status} for o in objectives],
        "budget": {
            "limit_cents": budget.limit_cents if budget else 0,
            "spent_cents": budget.spent_cents if budget else 0,
        },
        "agents": [
            {"role": a.role.value, "name": a.name, "status": a.status.value} for a in agents
        ],
        "active_task_count": int(active_tasks or 0),
        "cycle": {"active": cycle.active, "can_start": cycle.can_start, "reason": cycle.reason},
        "pending_decisions": [
            {"id": str(d.id), "kind": d.kind.value, "summary": (d.summary or "")[:400]}
            for d in pending
        ],
    }


async def _call_tool(db, user_id: uuid.UUID, mid, params: dict) -> dict:
    name = params.get("name")
    args = params.get("arguments") or {}
    try:
        if name == "list_companies":
            rows = (
                await db.scalars(
                    select(Company)
                    .join(Membership, Membership.company_id == Company.id)
                    .where(Membership.user_id == user_id)
                    .order_by(Company.created_at.desc())
                )
            ).all()
            return _ok(
                mid,
                _content(
                    {
                        "companies": [
                            {"id": str(c.id), "name": c.name, "status": c.status.value}
                            for c in rows
                        ]
                    }
                ),
            )

        if name == "create_company":
            user = await db.get(User, user_id)
            if user is None:
                return _error(mid, -32000, "user not found")
            company = await onboarding.start(
                db,
                user=user,
                mission_text=str(args["mission_text"]),
                budget_cents=int(args["budget_cents"]),
                constraints=args.get("constraints"),
                involvement=args.get("involvement"),
            )
            await db.commit()
            return _ok(
                mid, _content({"company_id": str(company.id), "status": company.status.value})
            )

        if name == "generate_org":
            company = await _founder_company(db, user_id, args.get("company_id"))
            preview = await onboarding.generate(db, company=company)
            await db.commit()
            return _ok(mid, _content(preview))

        if name == "refine_plan":
            company = await _founder_company(db, user_id, args.get("company_id"))
            preview = await onboarding.refine(db, company=company, message=str(args["message"]))
            await db.commit()
            return _ok(mid, _content(preview))

        if name == "launch_company":
            company = await _founder_company(db, user_id, args.get("company_id"))
            if company.status is not CompanyStatus.draft:
                return _error(mid, -32000, f"company is {company.status.value}, not draft")
            task_id = await onboarding.launch(db, company=company)
            await db.commit()
            if task_id is not None:
                await enqueue_task(task_id)
            return _ok(mid, _content({"status": "active", "launched": task_id is not None}))

        if name == "get_company_snapshot":
            company = await _founder_company(db, user_id, args.get("company_id"))
            return _ok(mid, _content(await _snapshot(db, company)))

        if name == "list_decisions":
            company = await _founder_company(db, user_id, args.get("company_id"))
            pending = (
                await db.scalars(
                    select(DecisionRequest)
                    .where(
                        DecisionRequest.company_id == company.id,
                        DecisionRequest.status == DecisionStatus.pending,
                    )
                    .order_by(DecisionRequest.created_at)
                )
            ).all()
            return _ok(
                mid,
                _content(
                    {
                        "decisions": [
                            {
                                "id": str(d.id),
                                "kind": d.kind.value,
                                "summary": (d.summary or "")[:600],
                            }
                            for d in pending
                        ]
                    }
                ),
            )

        if name in ("approve_decision", "reject_decision"):
            company = await _founder_company(db, user_id, args.get("company_id"))
            try:
                decision_id = uuid.UUID(str(args["decision_id"]))
            except (ValueError, TypeError):
                return _error(mid, -32602, "invalid decision_id")
            decision = await db.get(DecisionRequest, decision_id)
            if decision is None or decision.company_id != company.id:
                return _error(mid, -32000, "decision not found")
            if decision.status is not DecisionStatus.pending:
                return _error(mid, -32000, f"decision already {decision.status.value}")
            resumed = await resolve_decision(
                db,
                decision,
                approved=(name == "approve_decision"),
                user_id=user_id,
                note=args.get("note"),
            )
            await db.commit()
            if resumed is not None:
                await enqueue_task(resumed)
            return _ok(
                mid,
                _content({"resolved": decision.status.value, "task_resumed": resumed is not None}),
            )

        if name == "run_cycle":
            company = await _founder_company(db, user_id, args.get("company_id"))
            result = await runs_svc.start_cycle(db, company)
            if result.started and result.task_id is not None:
                await db.commit()
                await enqueue_task(result.task_id)
            return _ok(mid, _content({"started": result.started, "reason": result.reason}))

        if name == "set_playbook":
            company = await _founder_company(db, user_id, args.get("company_id"))
            company.playbook = str(args.get("playbook") or "").strip()
            await db.commit()
            return _ok(mid, _content({"ok": True, "customized": bool(company.playbook)}))

        return _error(mid, -32601, f"unknown tool: {name}")
    except OnboardingError as exc:
        return _error(mid, -32000, f"onboarding: {exc}")
    except HTTPException as exc:
        return _error(mid, -32000, exc.detail)
    except KeyError as exc:
        return _error(mid, -32602, f"missing argument: {exc}")
