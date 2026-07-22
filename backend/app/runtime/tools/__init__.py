"""Agent tool registry — auto-discovers per-area tool modules.

Every sibling module (``core``, ``sales``, ``marketing``, ``ops``, ``finance``,
``legal``, …) that defines ``SPECS`` / ``HANDLERS`` is registered automatically,
so a new tool is added by editing one area module — never this file. ``core``
is ordered first; the rest follow alphabetically.

Tool discovery / hot-loading
----------------------------
An agent does NOT receive every tool up front. Each task starts with a small,
always-available **core** set (orchestration, grounding, escalation, and the two
discovery tools themselves — see :data:`CORE_TOOL_NAMES`); the much larger long
tail of domain tools is *discoverable*. The agent finds what exists with
``discover_tools`` and hot-loads what it needs with ``use_tool``; the native
backend then includes those tools' specs on subsequent steps. This keeps each
request's tool list small and focused without removing any capability — and it is
distinct from ``request_capability`` (for a tool that does NOT exist yet).

Public API:
- ``TOOL_SPECS``: the flat list of every tool's :class:`ToolSpec` (the full catalog).
- ``CORE_TOOL_NAMES``: the always-loaded tool names.
- ``core_specs()`` / ``specs_for(names)``: the specs to send the model.
- ``discoverable_catalog(...)`` / ``resolve_tool_names(...)`` / ``tool_category(...)``:
  back the ``discover_tools`` / ``use_tool`` tools.
- ``execute_tool(db, ctx, *, agent, task, name, args)``: dispatch by name.
- ``ToolOutcome``: the handler return type.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable

from app.providers.base import ToolSpec
from app.runtime.tools.base import Handler, ToolOutcome

_EXCLUDE = {"base"}

#: Tools every agent always has, regardless of discovery. These are the loop's
#: control surface (it ends on ``report_result``), the grounding/memory and
#: escalation primitives, the platform escalation path (``request_capability`` /
#: ``report_bug`` — kept always-on so a genuine capability gap is never blocked by
#: discovery), the skill loader, and the discovery tools themselves. Everything
#: else is discoverable on demand.
CORE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # discovery / hot-loading
        "discover_tools",
        "use_tool",
        # task lifecycle & delegation
        "report_result",
        "dispatch_task",
        "dispatch_tasks",
        "collect_results",
        "submit_plan",
        # grounding & memory
        "write_memory",
        "read_metrics",
        "record_metric",
        # escalation to the founder / CEO
        "request_decision",
        "request_budget",
        "request_secret",
        "request_user_action",
        # live, ephemeral founder-facing milestone updates
        "post_mission_update",
        # platform escalation (a tool that does NOT exist yet) — never gated
        "request_capability",
        "report_bug",
        # self-service tool acquisition (connect a service that ALREADY exists) —
        # kept always-on so an agent can wire up a needed tool without the founder.
        # `connect_service` registers an external MCP server; `configure_integration`
        # supplies credentials for a first-class built-in integration (Cloudflare).
        "connect_service",
        "configure_integration",
        # reusable playbooks
        "load_skill",
    }
)

#: A few tools live in the ``core`` module but are domain capabilities, not control
#: primitives; give them a user-facing discovery category instead of "core".
_CATEGORY_OVERRIDE: dict[str, str] = {
    "web_search": "research",
    "web_fetch": "research",
    "send_email": "comms",
    "register_domain": "marketing",
}


def _load() -> tuple[list[ToolSpec], dict[str, Handler], dict[str, str]]:
    names = [m.name for m in pkgutil.iter_modules(__path__) if m.name not in _EXCLUDE]
    # core first, then the area modules alphabetically (stable tool ordering).
    names.sort(key=lambda n: (n != "core", n))

    specs: list[ToolSpec] = []
    handlers: dict[str, Handler] = {}
    category: dict[str, str] = {}
    for name in names:
        mod = importlib.import_module(f"{__name__}.{name}")
        for spec in getattr(mod, "SPECS", []):
            specs.append(spec)
            # First module to declare a tool name owns its category (core wins, as
            # it is processed first). Overrides reclassify a handful of core tools.
            category.setdefault(spec.name, _CATEGORY_OVERRIDE.get(spec.name, name))
        for tool_name, handler in getattr(mod, "HANDLERS", {}).items():
            if tool_name in handlers:
                raise RuntimeError(f"duplicate tool name {tool_name!r} (module {name})")
            handlers[tool_name] = handler
    return specs, handlers, category


TOOL_SPECS, _HANDLERS, _CATEGORY_BY_NAME = _load()

# Name → spec, de-duplicated (a couple of legacy specs share a name); first wins,
# matching the category map above.
_SPEC_BY_NAME: dict[str, ToolSpec] = {}
for _spec in TOOL_SPECS:
    _SPEC_BY_NAME.setdefault(_spec.name, _spec)


def _summarize(spec: ToolSpec, limit: int = 160) -> str:
    """A one-line summary of a tool, for the discovery catalog.

    Takes the first sentence of the tool's description (so the catalog stays compact)
    and clips it, so discovering N tools costs a line each rather than full schemas.
    """
    text = " ".join((spec.description or "").split())
    head, _, _ = text.partition(". ")
    head = head.rstrip(".")
    if len(head) > limit:
        head = head[: limit - 1].rstrip() + "…"
    return head or spec.name


def tool_category(name: str) -> str | None:
    """The discovery category a tool belongs to (its area module), or ``None``."""
    return _CATEGORY_BY_NAME.get(name)


def is_known_tool(name: str) -> bool:
    """Whether ``name`` is a real built-in tool (core or discoverable)."""
    return name in _SPEC_BY_NAME


def all_categories() -> list[str]:
    """Discovery categories that contain at least one discoverable (non-core) tool."""
    cats = {
        cat for n, cat in _CATEGORY_BY_NAME.items() if n not in CORE_TOOL_NAMES and is_known_tool(n)
    }
    return sorted(cats)


def core_specs() -> list[ToolSpec]:
    """The always-loaded tool specs, in stable catalog order."""
    return [s for s in TOOL_SPECS if s.name in CORE_TOOL_NAMES and _SPEC_BY_NAME[s.name] is s]


def specs_for(active: Iterable[str]) -> list[ToolSpec]:
    """The tool specs to send the model: the core set ∪ the active (loaded) tools.

    De-duplicated and returned in stable catalog order (so the transcript and the
    provider call are deterministic across steps), and tolerant of unknown names
    (silently skipped — ``use_tool`` validates before a name ever lands here).
    """
    wanted = set(CORE_TOOL_NAMES) | {n for n in active if n in _SPEC_BY_NAME}
    seen: set[str] = set()
    out: list[ToolSpec] = []
    for spec in TOOL_SPECS:
        if spec.name in wanted and spec.name not in seen:
            seen.add(spec.name)
            out.append(spec)
    return out


def resolve_tool_names(names: Iterable[object]) -> tuple[list[str], list[str]]:
    """Split requested names into ``(loadable, unknown)``.

    ``loadable`` are real discoverable tools (core names are dropped — they are
    always present, so loading them is a no-op); ``unknown`` are names that match no
    built-in tool, so the caller can point the agent at ``request_capability``.
    Order-preserving and de-duplicated.
    """
    loadable: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for raw in names:
        n = str(raw or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        if n in CORE_TOOL_NAMES:
            continue  # already always-on
        if is_known_tool(n):
            loadable.append(n)
        else:
            unknown.append(n)
    return loadable, unknown


def discoverable_catalog(
    *,
    query: str | None = None,
    category: str | None = None,
    exclude: Iterable[str] = (),
) -> list[dict[str, str]]:
    """The discoverable (non-core) tools matching ``query`` / ``category``.

    Returns ``[{"name", "category", "summary"}, ...]`` sorted by category then name.
    ``query`` is a case-insensitive substring matched against the name, summary, and
    category; ``exclude`` drops already-active tools so discovery surfaces only what
    is not yet loaded.
    """
    q = (query or "").strip().lower()
    cat = (category or "").strip().lower() or None
    skip = set(exclude)
    rows: list[dict[str, str]] = []
    for spec in TOOL_SPECS:
        name = spec.name
        if name in CORE_TOOL_NAMES or name in skip:
            continue
        if _SPEC_BY_NAME[name] is not spec:  # de-dupe legacy shared names
            continue
        tcat = _CATEGORY_BY_NAME.get(name, "other")
        if cat and tcat != cat:
            continue
        summary = _summarize(spec)
        if q and q not in name.lower() and q not in summary.lower() and q not in tcat.lower():
            continue
        rows.append({"name": name, "category": tcat, "summary": summary})
    rows.sort(key=lambda r: (r["category"], r["name"]))
    return rows


async def execute_tool(db, ctx, *, agent, task, name: str, args: dict) -> ToolOutcome:
    handler = _HANDLERS.get(name)
    if handler is None:
        return ToolOutcome(observation=f"unknown tool {name}")
    if not isinstance(args, dict):
        args = {}
    try:
        return await handler(db, ctx, agent=agent, task=task, args=args)
    except (KeyError, ValueError, TypeError) as exc:
        # The model can emit a tool call with a missing or malformed argument
        # (e.g. dispatch_task without a "goal"). That must NOT crash the whole
        # task — roll back any partial writes and hand the model a recoverable
        # error it can correct on the next step.
        await db.rollback()
        detail = (
            f"missing argument {exc.args[0]!r}"
            if isinstance(exc, KeyError) and exc.args
            else str(exc)
        )
        return ToolOutcome(
            observation=f"tool {name} failed: invalid arguments ({detail}).",
            is_error=True,
        )


__all__ = [
    "TOOL_SPECS",
    "CORE_TOOL_NAMES",
    "core_specs",
    "specs_for",
    "resolve_tool_names",
    "discoverable_catalog",
    "tool_category",
    "all_categories",
    "is_known_tool",
    "execute_tool",
    "ToolOutcome",
]
