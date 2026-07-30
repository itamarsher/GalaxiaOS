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
from app.integrations.files import FileProviderError
from app.models import (
    Agent,
    Budget,
    Company,
    CompanyFile,
    DecisionRequest,
    Membership,
    Objective,
    Task,
    User,
)
from app.models.enums import (
    AgentRole,
    AgentStatus,
    CompanyStatus,
    DecisionStatus,
    TaskStatus,
)
from app.runtime.queue import enqueue_task
from app.services import (
    apikeys,
    founder_token,
    function_health,
    function_improvement,
    involvement,
    onboarding,
)
from app.services import artifacts as artifacts_svc
from app.services import chat as chat_svc
from app.services import company_reset as company_reset_svc
from app.services import files as files_svc
from app.services import governance as gov
from app.services import integrations as integrations_svc
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
        "name": "edit_mission",
        "description": "Change a company's mission (works on a live or draft company). Resets the "
        "company to a fresh 'draft', revising its mission text and/or constraints — this wipes the "
        "generated org and operational state (tasks, decisions, sites, memory, budget spend) but "
        "PRESERVES the budget limit, memberships (incl. your involvement / approval gates), and "
        "saved provider keys. After calling this, run generate_org then launch_company to relaunch "
        "on the new mission. Omit a field to keep its current value; an empty constraints list "
        "clears constraints.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "mission_text": {"type": "string", "description": "The revised mission."},
                "constraints": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["company_id"],
        },
    },
    {
        "name": "set_involvement",
        "description": "Set how you (the founder) want to be involved — the prose that drives which "
        "decisions escalate to you vs. auto-resolve. Name the decision kinds you must approve (e.g. "
        "'approve every plan, hire, spend increase, and outbound communication'). This is the lever "
        "that ARMS your approval gates; without it the delegate auto-approves. Takes effect "
        "immediately and survives a later edit_mission reset.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "involvement": {"type": "string", "description": "Your involvement, in prose."},
            },
            "required": ["company_id", "involvement"],
        },
    },
    {
        "name": "set_comms_approval",
        "description": "Turn the external-communications approval guardrail on or off. When ON, every "
        "outbound message (email, social/community post, published page) becomes a founder decision "
        "before it can send — recommended for agent-driven companies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "enabled": {"type": "boolean"},
            },
            "required": ["company_id", "enabled"],
        },
    },
    {
        "name": "get_function_health",
        "description": "Read the company's function-health board (RFC 0002): per-function KPI "
        "status (on_track/off_target/unmeasured) with current value and target, plus the "
        "agent-based KPIs. Use it to see which KPIs to instrument or retarget.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}},
            "required": ["company_id"],
        },
    },
    {
        "name": "set_health_target",
        "description": "Set (or clear) the target for one health KPI — what 'good' means for it. "
        "The improvement cycle measures off-target against this. 'metric' is a KPI name from "
        "get_function_health (e.g. 'signup_conversion_rate', 'agent_reliability'); omit 'target' "
        "or pass null to clear it.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "metric": {"type": "string", "description": "The KPI name to retarget."},
                "target": {"type": ["number", "null"], "description": "New target value, or null to clear."},
            },
            "required": ["company_id", "metric"],
        },
    },
    {
        "name": "add_provider_key",
        "description": "Store a BYOK model/provider API key for the company (encrypted at rest), "
        "replacing any active key for that provider. Use this to fund the company's own LLM/tooling "
        "usage instead of the managed free allowance. Returns only the provider + key fingerprint, "
        "never the key.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "provider": {
                    "type": "string",
                    "description": "e.g. 'anthropic', 'openai', 'openrouter', 'tavily'.",
                },
                "api_key": {"type": "string"},
            },
            "required": ["company_id", "provider", "api_key"],
        },
    },
    {
        "name": "get_storage_status",
        "description": "Whether the company has a working file store (a launch prerequisite). Reports "
        "if storage resolves and, if not, where a human founder can connect Google Drive. Agents "
        "can't persist reports/artifacts without it.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}},
            "required": ["company_id"],
        },
    },
    {
        "name": "connect_storage",
        "description": "Connect the company's file store over MCP by supplying a Google Drive "
        "OAuth refresh token (obtained once via Google consent). Verifies the token actually "
        "reaches Drive, then stores it envelope-encrypted — satisfying the storage prerequisite "
        "for launch_company without an in-app browser redirect. Optional 'root_folder_id' scopes "
        "where files are written (defaults to the Drive root). Never returns the token.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "refresh_token": {
                    "type": "string",
                    "description": "A Google Drive OAuth refresh token with drive.file scope.",
                },
                "root_folder_id": {
                    "type": "string",
                    "description": "Optional Drive folder id to scope writes under (default: root).",
                },
            },
            "required": ["company_id", "refresh_token"],
        },
    },
    {
        "name": "list_files",
        "description": "List documents the company's agents have saved to its file store (drafts, "
        "outreach sequences, models, briefs) — id, name, category, type, size. Agents often save "
        "deliverables here rather than as artifacts; read one in full with read_file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "limit": {"type": "integer", "description": "Max to return (default 100)."},
            },
            "required": ["company_id"],
        },
    },
    {
        "name": "read_file",
        "description": "Read one saved document in full from the company's file store — pass its "
        "file_id (from list_files) or its name. Returns the text content (base64 if binary). Use "
        "this to review a drafted outreach sequence, one-pager, or model an agent filed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "file_id": {"type": "string", "description": "The file's id from list_files."},
                "name": {"type": "string", "description": "Or match by file name (case-insensitive)."},
            },
            "required": ["company_id"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete one saved document from the company's file store by file_id (from "
        "list_files) — removes the tracking row and best-effort deletes the stored blob. Use to "
        "clean up superseded drafts / duplicate versions so there's one source of truth.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "file_id": {"type": "string"},
            },
            "required": ["company_id", "file_id"],
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
        "name": "get_decision",
        "description": "Read ONE founder decision in full — the complete, untruncated summary plus "
        "its structured payload (e.g. the exact outbound message body, recipient, or proposed "
        "spend). list_decisions truncates for the list view; use this to review the actual content "
        "before you approve_decision / reject_decision (e.g. an outbound email awaiting comms approval).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "decision_id": {"type": "string"},
            },
            "required": ["company_id", "decision_id"],
        },
    },
    {
        "name": "list_artifacts",
        "description": "List the founder-facing deliverables agents have produced (reports, briefs, "
        "positioning docs, drafts) — id, kind, title, and when. These are internal documents the "
        "company saved for you; read one in full with read_artifact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "limit": {"type": "integer", "description": "Max to return (default 50)."},
            },
            "required": ["company_id"],
        },
    },
    {
        "name": "read_artifact",
        "description": "Read one deliverable in full (its markdown body) by id — e.g. a positioning "
        "one-pager or a drafted piece of outbound material an agent saved as a report.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "artifact_id": {"type": "string"},
            },
            "required": ["company_id", "artifact_id"],
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
    {
        "name": "list_agents",
        "description": "List the company's agents (the fleet): id, role, name, and status "
        "(active/paused). Use the ids to pause/resume, and the roles to send_founder_message.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}},
            "required": ["company_id"],
        },
    },
    {
        "name": "send_founder_message",
        "description": "Send a founder message to one agent (by role) to steer it live — adjust its "
        "priorities, hand it information (e.g. web-research findings), or redirect its work. If the "
        "agent is idle a task is spawned to act on it; if it's waiting on your reply, this resumes "
        "it. This is how you steer without waiting for a decision.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "string"},
                "agent_role": {
                    "type": "string",
                    "description": "Which agent to message, e.g. 'ceo', 'growth', 'product', 'design'.",
                },
                "message": {"type": "string"},
            },
            "required": ["company_id", "agent_role", "message"],
        },
    },
    {
        "name": "pause_agent",
        "description": "Pause an agent (by id): it stops taking on work until resumed. Use to hold "
        "a function while you redirect the company.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}, "agent_id": {"type": "string"}},
            "required": ["company_id", "agent_id"],
        },
    },
    {
        "name": "resume_agent",
        "description": "Resume a paused agent (by id) so it takes on work again.",
        "inputSchema": {
            "type": "object",
            "properties": {"company_id": {"type": "string"}, "agent_id": {"type": "string"}},
            "required": ["company_id", "agent_id"],
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


def _connect_doc() -> dict:
    """The public agent-onboarding recipe: how to register, mint a founder token,
    connect this MCP server, and operate — plus the live tool catalog and a
    ready-to-paste block. Everything an agent needs to bootstrap without reading source."""
    base = settings.public_api_base_url.rstrip("/") if settings.public_api_base_url else ""
    mcp_url = f"{base}/connect/founder" if base else "/connect/founder"
    b = base or "https://<your-abos-host>"
    paste = (
        "Register and operate a company on ABOS via its MCP server.\n"
        f"Base URL: {b}\n\n"
        f'1. Create an account:  POST {b}/auth/signup  {{"email":"you@example.com","password":"…"}}'
        "  → save access_token  (already have one? POST /auth/login)\n"
        f"2. Mint a founder token:  POST {b}/founder/connection  "
        'with header  Authorization: Bearer <access_token>  → save "token"\n'
        f"3. Add this MCP server to your agent:  URL {mcp_url}  "
        "header  Authorization: Bearer <token>\n"
        "4. Operate:  create_company → generate_org → launch_company;  then steer with "
        "get_company_snapshot, list_decisions, approve_decision / reject_decision."
    )
    return {
        "server": _SERVER_INFO,
        "base_url": base or None,
        "mcp_url": mcp_url,
        "bootstrap": [
            {"step": 1, "action": "create account", "method": "POST", "path": "/auth/signup",
             "body": {"email": "you@example.com", "password": "…"}, "returns": "access_token"},
            {"step": 2, "action": "mint founder token", "method": "POST",
             "path": "/founder/connection", "auth": "Bearer <access_token>",
             "returns": "founder connection token"},
            {"step": 3, "action": "connect this MCP server", "mcp_url": mcp_url,
             "auth": "Bearer <founder token>"},
            {"step": 4, "action": "operate",
             "tools": ["create_company", "generate_org", "launch_company"]},
        ],
        "tools": [{"name": t["name"], "description": t["description"]} for t in _TOOL_SPECS],
        "paste_to_agent": paste,
    }


@router.get("/connect")
async def connect_discovery():
    """Public, unauthenticated: point an AI agent here to learn how to register,
    connect, and operate a company over MCP — no source-reading required."""
    return _connect_doc()


@router.post("/connect/founder")
async def founder_mcp(request: Request, db: DbDep):
    # Introspection (initialize / tools/list) is token-optional so an agent can point
    # at this URL and discover the surface; every tools/call still requires a valid
    # founder token (minted at POST /founder/connection — see GET /connect).
    user_id = founder_token.verify(_bearer(request))

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
        if user_id is None:
            return _error(
                mid,
                -32001,
                "authenticate first: create an account (POST /auth/signup), mint a founder "
                "token (POST /founder/connection with your access token), then set header "
                "Authorization: Bearer <token>. Full recipe: GET /connect.",
            )
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

        if name == "edit_mission":
            company = await _founder_company(db, user_id, args.get("company_id"))
            mt = args.get("mission_text")
            fresh = await company_reset_svc.reset_company(
                db,
                company=company,
                mission_text=str(mt) if mt is not None else None,
                constraints=args.get("constraints"),
            )
            await db.commit()
            return _ok(
                mid,
                _content(
                    {
                        "company_id": str(fresh.id),
                        "status": fresh.status.value,
                        "next": "generate_org, then launch_company",
                    }
                ),
            )

        if name == "set_involvement":
            company = await _founder_company(db, user_id, args.get("company_id"))
            await involvement.set_involvement(
                db, company_id=company.id, user_id=user_id, text=str(args["involvement"])
            )
            await db.commit()
            return _ok(mid, _content({"ok": True, "gates_armed": True}))

        if name == "set_comms_approval":
            company = await _founder_company(db, user_id, args.get("company_id"))
            enabled = await gov.set_external_comms_approval(
                db, company_id=company.id, enabled=bool(args["enabled"])
            )
            await db.commit()
            return _ok(mid, _content({"external_comms_approval": enabled}))

        if name == "get_function_health":
            company = await _founder_company(db, user_id, args.get("company_id"))
            board = await function_improvement.health_board(db, company_id=company.id)
            return _ok(mid, _content(board))

        if name == "set_health_target":
            company = await _founder_company(db, user_id, args.get("company_id"))
            raw = args.get("target")
            target = float(raw) if isinstance(raw, (int, float)) else None
            try:
                result = await function_health.set_target(
                    db, company_id=company.id, metric=str(args["metric"]), target=target
                )
            except ValueError as exc:
                return _error(mid, -32602, str(exc))
            await db.commit()
            return _ok(mid, _content(result))

        if name == "add_provider_key":
            company = await _founder_company(db, user_id, args.get("company_id"))
            key = await apikeys.store_key(
                db,
                company_id=company.id,
                provider=str(args["provider"]).lower().strip(),
                plaintext=str(args["api_key"]),
            )
            await db.commit()
            return _ok(
                mid,
                _content(
                    {
                        "provider": key.provider,
                        "key_fingerprint": key.key_fingerprint,
                        "status": key.status.value,
                    }
                ),
            )

        if name == "get_storage_status":
            company = await _founder_company(db, user_id, args.get("company_id"))
            provider = await integrations_svc.resolve_file_provider(db, company_id=company.id)
            status_out = await integrations_svc.google_drive_status(db, company_id=company.id)
            return _ok(
                mid,
                _content(
                    {
                        "storage_resolves": provider is not None,
                        "managed_default_available": integrations_svc.managed_store_configured(),
                        "connect_available": status_out.get("connect_available"),
                        "connect_hint": (
                            None
                            if provider is not None
                            else "Connect it agent-side by calling connect_storage with a Google "
                            "Drive OAuth refresh_token, or a human founder connects Drive once at "
                            "/auth/google/drive/connect (account-wide) or in Settings → Integrations."
                        ),
                    }
                ),
            )

        if name == "connect_storage":
            company = await _founder_company(db, user_id, args.get("company_id"))
            refresh_token = str(args.get("refresh_token") or "").strip()
            if not refresh_token:
                return _error(mid, -32602, "refresh_token is required")
            if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
                return _error(
                    mid,
                    -32000,
                    "this deployment has no Google OAuth app configured, so a Drive refresh "
                    "token cannot be verified here",
                )
            raw_root = args.get("root_folder_id")
            root_folder_id = str(raw_root).strip() if raw_root else None
            try:
                await integrations_svc.verify_google_drive(
                    client_id=settings.google_oauth_client_id,
                    client_secret=settings.google_oauth_client_secret,
                    refresh_token=refresh_token,
                    root_folder_id=root_folder_id or "root",
                )
            except FileProviderError as exc:
                return _error(mid, -32000, f"drive credentials rejected: {exc}")
            await integrations_svc.set_google_drive_refresh(
                db, company_id=company.id, refresh_token=refresh_token, root_folder_id=root_folder_id
            )
            await db.commit()
            return _ok(mid, _content({"connected": True, "storage_resolves": True}))

        if name == "launch_company":
            company = await _founder_company(db, user_id, args.get("company_id"))
            if company.status is not CompanyStatus.draft:
                return _error(mid, -32000, f"company is {company.status.value}, not draft")
            task_id = await onboarding.launch(db, company=company)
            await db.commit()
            if task_id is not None:
                await enqueue_task(task_id)
            return _ok(mid, _content({"status": "active", "launched": task_id is not None}))

        if name == "list_files":
            company = await _founder_company(db, user_id, args.get("company_id"))
            rows = await files_svc.list_files(
                db, company_id=company.id, limit=int(args.get("limit") or 100)
            )
            return _ok(
                mid,
                _content(
                    {
                        "files": [
                            {
                                "id": str(f.id),
                                "name": f.name,
                                "category": f.category.value,
                                "mime_type": f.mime_type,
                                "size_bytes": f.size_bytes,
                                "description": f.description,
                            }
                            for f in rows
                        ]
                    }
                ),
            )

        if name == "read_file":
            company = await _founder_company(db, user_id, args.get("company_id"))
            f = None
            if args.get("file_id"):
                try:
                    f = await db.get(CompanyFile, uuid.UUID(str(args["file_id"])))
                except (ValueError, TypeError):
                    return _error(mid, -32602, "invalid file_id")
                if f is not None and f.company_id != company.id:
                    f = None
            elif args.get("name"):
                f = await files_svc.find_file(db, company_id=company.id, name=str(args["name"]))
            else:
                return _error(mid, -32602, "provide file_id or name")
            if f is None:
                return _error(mid, -32000, "file not found")
            if not f.external_id:
                return _error(mid, -32000, "file has no stored content to read")
            provider = await integrations_svc.resolve_file_provider(db, company_id=company.id)
            if provider is None:
                return _error(mid, -32000, "no file store configured for this company")
            try:
                raw = await provider.download_file(f.external_id)
            except FileProviderError as exc:
                return _error(mid, -32000, f"could not read file: {exc}")
            max_bytes = 300_000
            body = raw[:max_bytes]
            try:
                content = body.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                import base64

                content = base64.b64encode(body).decode()
                encoding = "base64"
            return _ok(
                mid,
                _content(
                    {
                        "id": str(f.id),
                        "name": f.name,
                        "category": f.category.value,
                        "mime_type": f.mime_type,
                        "size_bytes": f.size_bytes,
                        "encoding": encoding,
                        "truncated": len(raw) > max_bytes,
                        "content": content,
                    }
                ),
            )

        if name == "delete_file":
            company = await _founder_company(db, user_id, args.get("company_id"))
            try:
                fid = uuid.UUID(str(args["file_id"]))
            except (ValueError, TypeError):
                return _error(mid, -32602, "invalid file_id")
            deleted = await files_svc.delete_file(db, company_id=company.id, file_id=fid)
            if not deleted:
                return _error(mid, -32000, "file not found")
            await db.commit()
            return _ok(mid, _content({"deleted": True, "file_id": str(fid)}))

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

        if name == "get_decision":
            company = await _founder_company(db, user_id, args.get("company_id"))
            try:
                did = uuid.UUID(str(args["decision_id"]))
            except (ValueError, TypeError):
                return _error(mid, -32602, "invalid decision_id")
            d = await db.get(DecisionRequest, did)
            if d is None or d.company_id != company.id:
                return _error(mid, -32000, "decision not found")
            return _ok(
                mid,
                _content(
                    {
                        "id": str(d.id),
                        "kind": d.kind.value,
                        "status": d.status.value,
                        "summary": d.summary or "",
                        "payload": d.payload,
                        "agent_id": str(d.agent_id) if d.agent_id else None,
                        "created_at": d.created_at.isoformat() if d.created_at else None,
                    }
                ),
            )

        if name == "list_artifacts":
            company = await _founder_company(db, user_id, args.get("company_id"))
            rows = await artifacts_svc.list_artifacts(
                db, company_id=company.id, limit=int(args.get("limit") or 50)
            )
            return _ok(
                mid,
                _content(
                    {
                        "artifacts": [
                            {
                                "id": str(a.id),
                                "kind": a.kind,
                                "title": a.title,
                                "created_at": a.created_at.isoformat() if a.created_at else None,
                            }
                            for a in rows
                        ]
                    }
                ),
            )

        if name == "read_artifact":
            company = await _founder_company(db, user_id, args.get("company_id"))
            try:
                aid = uuid.UUID(str(args["artifact_id"]))
            except (ValueError, TypeError):
                return _error(mid, -32602, "invalid artifact_id")
            a = await artifacts_svc.get_artifact(db, company_id=company.id, artifact_id=aid)
            if a is None:
                return _error(mid, -32000, "artifact not found")
            return _ok(
                mid,
                _content(
                    {
                        "id": str(a.id),
                        "kind": a.kind,
                        "title": a.title,
                        "body_md": a.body_md,
                        "source_agent_id": str(a.source_agent_id) if a.source_agent_id else None,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
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

        if name == "list_agents":
            company = await _founder_company(db, user_id, args.get("company_id"))
            agents = (
                await db.scalars(
                    select(Agent).where(Agent.company_id == company.id).order_by(Agent.created_at)
                )
            ).all()
            return _ok(
                mid,
                _content(
                    {
                        "agents": [
                            {
                                "id": str(a.id),
                                "role": a.role.value,
                                "name": a.name,
                                "status": a.status.value,
                            }
                            for a in agents
                        ]
                    }
                ),
            )

        if name == "send_founder_message":
            company = await _founder_company(db, user_id, args.get("company_id"))
            try:
                role = AgentRole(str(args["agent_role"]))
            except ValueError:
                return _error(mid, -32602, f"unknown agent_role: {args.get('agent_role')}")
            agent = await db.scalar(
                select(Agent)
                .where(
                    Agent.company_id == company.id,
                    Agent.role == role,
                    Agent.status == AgentStatus.active,
                )
                .order_by(Agent.created_at)
            )
            if agent is None:
                return _error(mid, -32000, f"no active '{role.value}' agent in this company")
            channel = await chat_svc.founder_dm(db, company_id=company.id, agent_id=agent.id)
            _, woken = await chat_svc.post_message(
                db,
                company_id=company.id,
                channel_id=channel.id,
                sender_agent_id=None,
                body=str(args["message"]),
            )
            spawned = None
            if not woken:
                spawned = await chat_svc.spawn_dm_handler_task(
                    db,
                    company_id=company.id,
                    channel=channel,
                    agent_id=agent.id,
                    founder_message=str(args["message"]),
                )
            await db.commit()
            for tid in woken:
                await enqueue_task(tid)
            if spawned is not None:
                await enqueue_task(spawned)
            return _ok(
                mid,
                _content(
                    {
                        "delivered_to": role.value,
                        "resumed": bool(woken),
                        "spawned": spawned is not None,
                    }
                ),
            )

        if name in ("pause_agent", "resume_agent"):
            company = await _founder_company(db, user_id, args.get("company_id"))
            try:
                agent_id = uuid.UUID(str(args["agent_id"]))
            except (ValueError, TypeError):
                return _error(mid, -32602, "invalid agent_id")
            agent = await db.get(Agent, agent_id)
            if agent is None or agent.company_id != company.id:
                return _error(mid, -32000, "agent not found")
            agent.status = AgentStatus.paused if name == "pause_agent" else AgentStatus.active
            await db.commit()
            return _ok(mid, _content({"agent_id": str(agent.id), "status": agent.status.value}))

        return _error(mid, -32601, f"unknown tool: {name}")
    except OnboardingError as exc:
        return _error(mid, -32000, f"onboarding: {exc}")
    except HTTPException as exc:
        return _error(mid, -32000, exc.detail)
    except KeyError as exc:
        return _error(mid, -32602, f"missing argument: {exc}")
