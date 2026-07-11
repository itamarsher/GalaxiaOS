"""Self-service tool acquisition: let an agent connect the service that
implements the tools it needs, instead of waiting on the founder.

Until now, only a founder could wire up an external tool server (Settings → MCP
servers). That left an agent stuck the moment it needed a capability no built-in
tool covered but that a standard tool server already implements: its only moves
were ``request_user_action`` (ask the founder to connect it) or
``request_capability`` (ask the Platform agent to build it) — both of which park
the work behind a human. ``connect_service`` closes that gap: the agent
registers the service's MCP endpoint itself, ABOS probes it, and the service's
tools become available — namespaced ``mcp__{slug}__*`` — for the agent to call on
its NEXT step, in the same run. This is the agent-facing counterpart to the
founder's Settings flow (:mod:`app.services.mcp`), and it is distinct from
``request_capability`` (a tool that does NOT exist yet): ``connect_service`` wires
up a tool that already exists behind a reachable server.

Honest-by-design, like every other seam: registration probes the server
(``tools/list``) and reports the real outcome. A bad URL, an auth failure, or an
unreachable host is surfaced as an error — never a fabricated "connected", and a
brand-new registration that can't be probed is rolled back so a broken server
never lingers in the company's config.

Self-registration does NOT weaken governance. Registering a server is a config
action; every *call* to a connected tool still passes the same external-egress
gate as any other MCP tool (the native backend marks MCP calls ``is_external``),
so a policy can require founder approval or deny it. An agent can wire up a tool
without being able to silently exfiltrate through it. And it never clobbers a
working server the founder already configured under the same name — an existing,
healthy connection is reported as already-available instead of being overwritten.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.config import settings
from app.models import Agent, Task
from app.models.enums import MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import mcp as mcp_svc
from app.services import mission_log

# How many exposed tool names to echo back to the agent, so connecting a large
# server doesn't flood the observation. The full set is offered on the next step.
_MAX_TOOLS_SHOWN = 25


#: Built-in integrations ABOS has its OWN adapter for (not MCP), and that an agent
#: can therefore configure itself. Unlike ``connect_service`` (which registers an
#: external MCP tool server), these credentials feed native capabilities — site
#: hosting, custom domains, DNS (Cloudflare), and web search + page fetch (Tavily) —
#: that resolve through native adapters, not an ``mcp__*`` namespace.
_NATIVE_INTEGRATIONS = ("cloudflare", "tavily")


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="connect_service",
        description=(
            "Connect an external service (an MCP tool server) so YOU can start using the "
            "tools it implements — without waiting on the founder. Use this when you need a "
            "capability that a real service already provides behind a standard tool-server "
            "endpoint (e.g. a CRM, analytics, a project tracker, an internal API). Give the "
            "service a short name and its MCP endpoint URL (and an auth token if it needs one); "
            "ABOS registers it, probes it, and its tools become callable — namespaced "
            "`mcp__<name>__<tool>` — on your NEXT step. This is different from "
            "`request_capability` (which asks for a tool that does NOT exist yet): use "
            "`connect_service` for a tool that already exists behind a reachable server, and "
            "`request_capability` only when nothing implements it. If you don't know the "
            "endpoint URL, find it first (a tool skill via `load_skill`, or `web_search`); if "
            "the service needs credentials you don't have, `request_user_action` to ask the "
            "founder for them. Every call to a connected tool is still governed as external "
            "data egress, so sensitive sends may need founder approval."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Short service name, used to namespace its tools as "
                        "`mcp__<name>__*` (e.g. 'linear', 'acme_crm'). Reuse the same name "
                        "to reconnect the same service."
                    ),
                },
                "url": {
                    "type": "string",
                    "description": "The service's MCP endpoint URL (https).",
                },
                "auth_token": {
                    "type": "string",
                    "description": (
                        "Optional bearer token if the server requires auth. Stored "
                        "envelope-encrypted; never echoed back."
                    ),
                },
                "transport": {
                    "type": "string",
                    "description": "Transport, defaults to 'http'.",
                },
                "label": {
                    "type": "string",
                    "description": "Optional human-readable label (defaults to `name`).",
                },
            },
            "required": ["name", "url"],
        },
    ),
    ToolSpec(
        name="configure_integration",
        description=(
            "Configure credentials for a first-class BUILT-IN integration that powers ABOS's "
            "own native capabilities — site hosting, custom domains, and DNS — so you can turn "
            "those on yourself instead of asking the founder. This is different from "
            "`connect_service`: use `connect_service` to register an external MCP tool server, "
            "and `configure_integration` for a provider ABOS has its OWN adapter for (its "
            "credentials feed the native tools directly, not an `mcp__*` namespace). Sign up "
            "for the provider and self-issue a scoped API token, then pass it here; ABOS "
            "verifies the credentials before storing them envelope-encrypted, so a bad token is "
            "rejected up front. Supported: 'cloudflare' (needs `api_token` + `account_id`) — "
            "powers `publish_content` and `connect_domain`; 'tavily' (needs `api_key`) — powers "
            "`web_search` and `web_fetch`. Every downstream action is still governed and "
            "budget-metered as usual."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": list(_NATIVE_INTEGRATIONS),
                    "description": "The built-in integration to configure.",
                },
                "api_token": {
                    "type": "string",
                    "description": (
                        "A scoped API token for the provider (least privilege — the specific "
                        "zone/permissions you need, never a global key). Cloudflare."
                    ),
                },
                "account_id": {
                    "type": "string",
                    "description": "Cloudflare account id (required for provider 'cloudflare').",
                },
                "api_key": {
                    "type": "string",
                    "description": "Tavily API key (required for provider 'tavily').",
                },
            },
            "required": ["provider"],
        },
    ),
]


def _valid_url(url: str) -> bool:
    """A plausible ``http(s)`` endpoint — cheap guard before touching the network."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _tool_names(server) -> list[str]:
    return [t["name"] for t in (server.tools_cache or []) if isinstance(t, dict) and t.get("name")]


def _exposed(server) -> str:
    prefix = mcp_svc.tool_prefix(server.name)
    names = _tool_names(server)
    shown = ", ".join(f"{prefix}{n}" for n in names[:_MAX_TOOLS_SHOWN])
    if len(names) > _MAX_TOOLS_SHOWN:
        shown += f", … (+{len(names) - _MAX_TOOLS_SHOWN} more)"
    return shown


async def _connect_service(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if not settings.mcp_enabled:
        return ToolOutcome(
            observation=(
                "Connecting external tool servers is disabled on this deployment, so this "
                "did nothing. Ask the founder to enable it, or use `request_capability` if "
                "you need this capability built in."
            ),
            is_error=True,
        )

    name = str(args.get("name") or "").strip()
    url = str(args.get("url") or "").strip()
    if not name or not url:
        return ToolOutcome(
            observation="Provide both a service `name` and its MCP endpoint `url`.",
            is_error=True,
        )
    if not _valid_url(url):
        return ToolOutcome(
            observation=(
                f"{url!r} is not a valid http(s) URL for an MCP endpoint — nothing was "
                "connected. Find the service's tool-server endpoint and try again."
            ),
            is_error=True,
        )

    label = str(args.get("label") or name).strip() or name
    transport = str(args.get("transport") or "http").strip() or "http"
    auth_token = str(args.get("auth_token") or "").strip() or None

    slug = mcp_svc.normalize_name(name)
    existing = next(
        (s for s in await mcp_svc.list_servers(db, company_id=task.company_id) if s.name == slug),
        None,
    )
    # Never clobber a server that is already connected and working (it may be the
    # founder's own configuration). A healthy connection is idempotent — report it
    # as already-available rather than overwriting the URL/token.
    if existing is not None and existing.enabled and _tool_names(existing):
        return ToolOutcome(
            observation=(
                f"{label!r} is already connected ({len(_tool_names(existing))} tool(s) "
                f"available): {_exposed(existing)}. Use its tools directly — no need to "
                "reconnect."
            )
        )

    # ``add_server`` upserts by slug: for a brand-new name it inserts, for a broken
    # existing one it overwrites (safe — we only reach here when the existing server
    # has no working tools). Track whether we created it so a failed probe of a NEW
    # registration is rolled back instead of leaving a dead server behind.
    created = existing is None
    server = await mcp_svc.add_server(
        db,
        company_id=task.company_id,
        name=name,
        label=label,
        url=url,
        transport=transport,
        auth_token=auth_token,
    )
    await mcp_svc.refresh_tools(db, server=server)

    if server.last_error:
        detail = server.last_error
        if created:
            await mcp_svc.remove_server(db, company_id=task.company_id, server_id=server.id)
        return ToolOutcome(
            observation=(
                f"Could not connect {label!r}: {detail}. NOTHING was connected — check the "
                "URL and whether it needs an auth token, then try again, or "
                "`request_user_action` for the founder to supply credentials."
            ),
            is_error=True,
        )

    tools = _tool_names(server)
    if not tools:
        if created:
            await mcp_svc.remove_server(db, company_id=task.company_id, server_id=server.id)
        return ToolOutcome(
            observation=(
                f"Connected to {label!r}, but it exposes no tools — so there is nothing to "
                "use and it was not kept. Check that this is the right endpoint."
            ),
            is_error=True,
        )

    # Audit trail: a durable record that an agent self-connected a service, so the
    # founder can see (and, if they disagree, remove) it. Best-effort mission-log
    # beat keeps the live dashboard honest about new capabilities coming online.
    from app.services import memory as memory_svc

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Service connected: {label[:80]}",
        content=(
            f"{agent.name} ({agent.role.value}) connected the '{label}' tool server "
            f"({url}), exposing {len(tools)} tool(s): {', '.join(tools[:_MAX_TOOLS_SHOWN])}. "
            "Its tools are now available to the fleet, namespaced "
            f"'{mcp_svc.tool_prefix(server.name)}*'."
        ),
        source_task_id=task.id,
    )
    await mission_log.record(
        task.company_id,
        agent_id=agent.id,
        agent_name=agent.name,
        role=agent.role.value,
        headline=f"Connected {label} ({len(tools)} new tool(s))",
        kind="update",
    )

    return ToolOutcome(
        observation=(
            f"Connected {label!r}: {len(tools)} tool(s) now available — {_exposed(server)}. "
            "Call them directly; they are offered on your next step. Every call is governed "
            "as external data egress, so a sensitive send may need founder approval."
        )
    )


async def _configure_integration(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    provider = str(args.get("provider") or "").strip().lower()
    if provider not in _NATIVE_INTEGRATIONS:
        return ToolOutcome(
            observation=(
                f"Unknown built-in integration {provider!r}. Configurable ones: "
                f"{', '.join(_NATIVE_INTEGRATIONS)}. For any other service, register its MCP "
                "endpoint with `connect_service` instead."
            ),
            is_error=True,
        )
    if provider == "cloudflare":
        return await _configure_cloudflare(db, agent=agent, task=task, args=args)
    if provider == "tavily":
        return await _configure_tavily(db, agent=agent, task=task, args=args)
    # Guarded by the membership check above; kept exhaustive for future providers.
    return ToolOutcome(observation=f"{provider} is not configurable yet.", is_error=True)


async def _configure_cloudflare(db, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.integrations.cloudflare import verify_credentials
    from app.integrations.sitehost import SiteHostError
    from app.services import integrations as integrations_svc

    api_token = str(args.get("api_token") or "").strip()
    account_id = str(args.get("account_id") or "").strip()
    if not api_token or not account_id:
        return ToolOutcome(
            observation=(
                "Cloudflare needs both `api_token` (a scoped API token) and `account_id`. "
                "Create the token in the Cloudflare dashboard — least privilege, the specific "
                "zone and permissions you need — then pass both here."
            ),
            is_error=True,
        )

    # Verify before storing so a bad token/account is rejected up front — the same
    # honest check the founder's Settings flow does. Never store credentials we
    # haven't proven actually work.
    try:
        await verify_credentials(api_token, account_id)
    except SiteHostError as exc:
        return ToolOutcome(
            observation=(
                f"Cloudflare rejected these credentials: {exc}. NOTHING was stored — check the "
                "token's permissions and the account id, then try again."
            ),
            is_error=True,
        )

    await integrations_svc.set_cloudflare(
        db, company_id=task.company_id, api_token=api_token, account_id=account_id
    )

    from app.services import memory as memory_svc

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title="Integration configured: Cloudflare",
        content=(
            f"{agent.name} ({agent.role.value}) configured Cloudflare credentials for account "
            f"{account_id}. ABOS's native site-hosting, custom-domain, and DNS capabilities "
            "(`publish_content` / `connect_domain`) are now available to the fleet."
        ),
        source_task_id=task.id,
    )
    await mission_log.record(
        task.company_id,
        agent_id=agent.id,
        agent_name=agent.name,
        role=agent.role.value,
        headline="Configured Cloudflare (native hosting + DNS)",
        kind="update",
    )

    return ToolOutcome(
        observation=(
            "Cloudflare configured and verified. ABOS's built-in site-hosting, custom-domain, "
            "and DNS tools now work — load them with `use_tool` (e.g. `publish_content`, "
            "`connect_domain`) and use them directly. That's the NATIVE hosting flow; for "
            "generic Cloudflare API operations (cache purge, WAF, Workers) register the "
            "Cloudflare MCP server with `connect_service` instead."
        )
    )


#: BYO key slot under which a company's Tavily key is stored (matches
#: ``app.runtime.tools.core.WEB_SEARCH_PROVIDER`` — the same key powers web_search
#: and web_fetch).
_TAVILY_PROVIDER = "tavily"


async def _configure_tavily(db, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.integrations.tavily import verify_credentials
    from app.integrations.websearch import WebSearchError
    from app.services import apikeys

    api_key = str(args.get("api_key") or "").strip()
    if not api_key:
        return ToolOutcome(
            observation=(
                "Tavily needs an `api_key`. Sign up at tavily.com (the free tier issues a key "
                "with no card), copy the API key, then pass it here."
            ),
            is_error=True,
        )

    # Verify before storing so a bad key is rejected up front — the same honest
    # check the Cloudflare flow does. Never store a credential we haven't proven works.
    try:
        await verify_credentials(api_key)
    except WebSearchError as exc:
        return ToolOutcome(
            observation=(
                f"Tavily rejected this key: {exc}. NOTHING was stored — check the key and "
                "try again."
            ),
            is_error=True,
        )

    await apikeys.store_key(
        db, company_id=task.company_id, provider=_TAVILY_PROVIDER, plaintext=api_key
    )

    from app.services import memory as memory_svc

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title="Integration configured: Tavily",
        content=(
            f"{agent.name} ({agent.role.value}) configured a Tavily API key. ABOS's built-in "
            "web search and page-fetch tools (`web_search` / `web_fetch`) are now available to "
            "the fleet, billed against the company budget."
        ),
        source_task_id=task.id,
    )
    await mission_log.record(
        task.company_id,
        agent_id=agent.id,
        agent_name=agent.name,
        role=agent.role.value,
        headline="Configured Tavily (web search + page fetch)",
        kind="update",
    )

    return ToolOutcome(
        observation=(
            "Tavily configured and verified. `web_search` and `web_fetch` now work — load them "
            "with `use_tool` and use them directly. Each call is metered against the company "
            "budget."
        )
    )


HANDLERS = {
    "connect_service": _connect_service,
    "configure_integration": _configure_integration,
}
