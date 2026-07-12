"""Render deployment observability tools — let agents see our own deploys.

Read-only and free (no CostMeter charge): they only GET deploy/service status
from the Render API so the CEO/Platform agent can answer "did our last change
actually ship, and is it live?" — closing the visibility half of the dogfooding
deploy loop.

Credentials resolve like the issue tracker: a company's own BYOK ``render`` key
if set, otherwise the global ``ABOS_RENDER_API_KEY`` — but the global key is the
dogfooding account, so it is offered ONLY to the Galaxia company. Any other
tenant without its own key gets a "not connected" message, never another
company's Render account.
"""

from __future__ import annotations

from app.integrations.render import RenderClient, RenderError, get_render_client
from app.models import Agent, Task
from app.providers.base import ToolSpec
from app.runtime.tools.base import DEFAULT_MAX_OBSERVATION_CHARS, ToolOutcome, clip
from app.services import apikeys

#: Provider name under which a company's own Render key is stored (BYOK).
RENDER_PROVIDER = "render"

_NOT_CONNECTED = (
    "Render is not connected in this environment: no Render API key is available, "
    "so deployment status can't be read. Connect a Render key (Settings, provider "
    "'render') or set ABOS_RENDER_API_KEY. Nothing was read."
)

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="list_render_services",
        description=(
            "List the platform's Render services (our own deployments) with their type "
            "and dashboard URL, so you can see what services exist and pick a service id "
            "for the deploy tools. Read-only and free."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max services (default 20)."}
            },
        },
    ),
    ToolSpec(
        name="list_render_deploys",
        description=(
            "List recent deploys for a Render service (most recent first) with each "
            "deploy's status (e.g. live, build_in_progress, build_failed, canceled), the "
            "commit it shipped, and timestamps — so you can see whether our latest change "
            "deployed and is live. Read-only and free."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "The Render service id (srv-…)."},
                "limit": {"type": "integer", "description": "Max deploys (default 10)."},
            },
            "required": ["service_id"],
        },
    ),
    ToolSpec(
        name="get_render_deploy",
        description=(
            "Get one Render deploy's current status and commit by service id + deploy id "
            "— use to check whether a specific release finished and is live. Read-only "
            "and free."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "The Render service id (srv-…)."},
                "deploy_id": {"type": "string", "description": "The Render deploy id (dep-…)."},
            },
            "required": ["service_id", "deploy_id"],
        },
    ),
    ToolSpec(
        name="get_render_logs",
        description=(
            "Read recent log lines for a Render service (by service id) — use this to "
            "debug a failure: look for stack traces, errors, or crash output around when "
            "something went wrong. Read-only and free."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "service_id": {"type": "string", "description": "The Render service id (srv-…)."},
                "limit": {"type": "integer", "description": "Max log lines (default 50)."},
            },
            "required": ["service_id"],
        },
    ),
]


async def _resolve_client(db, company_id) -> RenderClient | None:
    """Company's own Render key if set; else the global key, Galaxia-only."""
    token = await apikeys.get_plaintext_key(
        db, company_id=company_id, provider=RENDER_PROVIDER
    )
    if token:
        return RenderClient(token)
    # The global key is the dogfooding Render account — only the platform company
    # may use it, so a tenant company never reaches our infra with a key it didn't
    # provide.
    from app.services import platform_company

    if await platform_company.is_platform_company(db, company_id):
        return get_render_client()
    return None


async def _list_render_services(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    client = await _resolve_client(db, task.company_id)
    if client is None:
        return ToolOutcome(observation=_NOT_CONNECTED, is_error=True)
    try:
        services = await client.list_services(limit=int(args.get("limit") or 20))
    except RenderError as exc:
        return ToolOutcome(observation=f"could not list Render services: {exc}", is_error=True)
    if not services:
        return ToolOutcome(observation="No Render services found for this account.")
    lines = [
        f"- {s.name} [{s.type}] id={s.id}"
        + (f" suspended={s.suspended}" if s.suspended and s.suspended != "not_suspended" else "")
        for s in services
    ]
    return ToolOutcome(observation=f"{len(services)} Render service(s):\n" + "\n".join(lines))


async def _list_render_deploys(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    client = await _resolve_client(db, task.company_id)
    if client is None:
        return ToolOutcome(observation=_NOT_CONNECTED, is_error=True)
    service_id = str(args.get("service_id") or "").strip()
    if not service_id:
        return ToolOutcome(observation="service_id is required", is_error=True)
    try:
        deploys = await client.list_deploys(service_id, limit=int(args.get("limit") or 10))
    except RenderError as exc:
        return ToolOutcome(observation=f"could not list deploys: {exc}", is_error=True)
    if not deploys:
        return ToolOutcome(observation=f"No deploys found for service {service_id}.")
    lines = [
        f"- {d.status} · {d.id} · {d.commit_id} {d.commit_message} · {d.created_at}"
        for d in deploys
    ]
    return ToolOutcome(
        observation=clip(
            f"{len(deploys)} deploy(s) for {service_id} (newest first):\n" + "\n".join(lines),
            DEFAULT_MAX_OBSERVATION_CHARS,
        )
    )


async def _get_render_deploy(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    client = await _resolve_client(db, task.company_id)
    if client is None:
        return ToolOutcome(observation=_NOT_CONNECTED, is_error=True)
    service_id = str(args.get("service_id") or "").strip()
    deploy_id = str(args.get("deploy_id") or "").strip()
    if not service_id or not deploy_id:
        return ToolOutcome(observation="service_id and deploy_id are required", is_error=True)
    try:
        d = await client.get_deploy(service_id, deploy_id)
    except RenderError as exc:
        return ToolOutcome(observation=f"could not get deploy: {exc}", is_error=True)
    return ToolOutcome(
        observation=(
            f"Deploy {d.id} on {service_id}: status={d.status}; "
            f"commit {d.commit_id} {d.commit_message}; "
            f"created {d.created_at}; finished {d.finished_at or '(unfinished)'}."
        )
    )


async def _get_render_logs(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    client = await _resolve_client(db, task.company_id)
    if client is None:
        return ToolOutcome(observation=_NOT_CONNECTED, is_error=True)
    service_id = str(args.get("service_id") or "").strip()
    if not service_id:
        return ToolOutcome(observation="service_id is required", is_error=True)
    try:
        logs = await client.get_logs(service_id, limit=int(args.get("limit") or 50))
    except RenderError as exc:
        return ToolOutcome(observation=f"could not read logs: {exc}", is_error=True)
    if not logs:
        return ToolOutcome(observation=f"No recent logs for service {service_id}.")
    lines = [f"{ln.timestamp} {ln.message}" for ln in logs]
    return ToolOutcome(
        observation=clip(
            f"Recent logs for {service_id} (oldest first):\n" + "\n".join(lines),
            DEFAULT_MAX_OBSERVATION_CHARS,
        )
    )


HANDLERS = {
    "list_render_services": _list_render_services,
    "list_render_deploys": _list_render_deploys,
    "get_render_deploy": _get_render_deploy,
    "get_render_logs": _get_render_logs,
}
