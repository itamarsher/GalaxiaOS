"""Tool discovery + hot-loading: find capabilities and load them on demand.

An agent starts each task with only the small **core** toolset (see
:data:`app.runtime.tools.CORE_TOOL_NAMES`). The full long tail of domain tools —
marketing, sales, finance, CRM, design, files, … — is *discoverable*: the agent
calls ``discover_tools`` to see what exists (a compact one-line catalog, not full
schemas) and ``use_tool`` to hot-load the ones it needs. The native backend then
includes those tools on the agent's subsequent steps, so each request carries a
small, relevant tool list instead of every tool at once.

This is deliberately distinct from ``request_capability``: ``use_tool`` loads a tool
that ALREADY EXISTS; ``request_capability`` asks the Platform agent to BUILD a tool
that does not exist yet. ``use_tool`` points the agent at ``request_capability`` when
it asks for a name that matches no built-in tool, so the two compose cleanly.
"""

from __future__ import annotations

from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome, truncation_notice

# How many catalog rows to return from a single discover_tools call, so a broad
# query can't dump the whole catalog into the context in one go.
_MAX_RESULTS = 40


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="discover_tools",
        description=(
            "Discover additional tools you can load. You start with a small core "
            "toolset; most domain capabilities (marketing, sales, finance, CRM, "
            "design, files, legal, ops, team management, web search, …) are loaded on "
            "demand. Search by keyword or browse a category to get a compact list of "
            "tool names + one-line summaries, then load the ones you need with "
            "`use_tool`. This does NOT load anything by itself. If nothing matches what "
            "you need, the capability may not exist yet — use `request_capability`."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keyword to match against tool names/summaries, e.g. 'email', 'invoice'.",
                },
                "category": {
                    "type": "string",
                    "description": "Optional category to browse (e.g. 'finance', 'marketing', 'crm').",
                },
            },
        },
    ),
    ToolSpec(
        name="use_tool",
        description=(
            "Hot-load one or more tools (by exact name, found via `discover_tools`) so "
            "you can call them on your next step. Loading is additive and persists for "
            "the rest of this task; loading a tool you already have is a harmless no-op. "
            "If a name matches no existing tool, it is reported back — use "
            "`request_capability` to ask for a tool that doesn't exist yet."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exact tool names to load, e.g. ['send_email', 'generate_image'].",
                },
            },
            "required": ["names"],
        },
    ),
]


async def _discover_tools(db, ctx, *, agent, task, args: dict) -> ToolOutcome:
    # Imported lazily: this module is imported while the tools package is still
    # initializing, so the catalog helpers aren't bound at module-import time.
    from app.runtime.tools import all_categories, discoverable_catalog

    query = args.get("query")
    category = args.get("category")
    rows = discoverable_catalog(query=query, category=category)
    if not rows:
        cats = ", ".join(all_categories())
        scope = []
        if query:
            scope.append(f"query {str(query)!r}")
        if category:
            scope.append(f"category {str(category)!r}")
        where = f" for {' and '.join(scope)}" if scope else ""
        return ToolOutcome(
            observation=(
                f"No loadable tools found{where}. Available categories: {cats}. "
                "If the capability you need isn't here, it may not exist yet — use "
                "`request_capability` to ask the Platform agent to build it."
            )
        )
    shown = rows[:_MAX_RESULTS]
    lines = [f"- {r['name']} [{r['category']}] — {r['summary']}" for r in shown]
    body = "\n".join(lines)
    if len(rows) > _MAX_RESULTS:
        body += truncation_notice(len(rows) - _MAX_RESULTS, "tools")
    return ToolOutcome(
        observation=(
            f"Loadable tools ({len(shown)} shown):\n{body}\n\n"
            'Load the ones you need with `use_tool({"names": [...]})`, then call them.'
        )
    )


async def _use_tool(db, ctx, *, agent, task, args: dict) -> ToolOutcome:
    """Validate the requested names and report what will be loaded.

    The actual activation (adding the names to the task's live tool set) is done by
    the native backend, which reads this same call — this handler owns the
    agent-facing confirmation and the unknown-name → ``request_capability`` nudge, so
    validation lives in one place (``resolve_tool_names``).
    """
    from app.runtime.tools import resolve_tool_names

    raw = args.get("names")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list) or not raw:
        return ToolOutcome(
            observation="Pass a non-empty `names` list of tool names to load.",
            is_error=True,
        )
    loadable, unknown = resolve_tool_names(raw)
    parts: list[str] = []
    if loadable:
        parts.append(
            f"Loaded {len(loadable)} tool(s): {', '.join(loadable)}. "
            "They are available on your next step — call them now."
        )
    # Names that were dropped because they're already core/always-on.
    requested = {str(n or "").strip() for n in raw if str(n or "").strip()}
    already = sorted(requested - set(loadable) - set(unknown))
    if already:
        parts.append(f"Already available (no load needed): {', '.join(already)}.")
    if unknown:
        parts.append(
            f"Not a known tool: {', '.join(unknown)}. If you need this capability and it "
            "doesn't exist yet, use `request_capability` to ask the Platform agent for it; "
            "otherwise check the exact name with `discover_tools`."
        )
    if not loadable and not already and unknown:
        return ToolOutcome(observation=" ".join(parts), is_error=True)
    return ToolOutcome(observation=" ".join(parts))


HANDLERS = {
    "discover_tools": _discover_tools,
    "use_tool": _use_tool,
}
