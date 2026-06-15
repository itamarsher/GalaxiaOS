"""Agent tool registry — auto-discovers per-area tool modules.

Every sibling module (``core``, ``sales``, ``marketing``, ``ops``, ``finance``,
``legal``, …) that defines ``SPECS`` / ``HANDLERS`` is registered automatically,
so a new tool is added by editing one area module — never this file. ``core``
is ordered first; the rest follow alphabetically.

Public API (unchanged from the old single-module ``tools``):
- ``TOOL_SPECS``: the flat list of every tool's :class:`ToolSpec`.
- ``execute_tool(db, ctx, *, agent, task, name, args)``: dispatch by name.
- ``ToolOutcome``: the handler return type.
"""

from __future__ import annotations

import importlib
import pkgutil

from app.providers.base import ToolSpec
from app.runtime.tools.base import Handler, ToolOutcome

_EXCLUDE = {"base"}


def _load() -> tuple[list[ToolSpec], dict[str, Handler]]:
    names = [m.name for m in pkgutil.iter_modules(__path__) if m.name not in _EXCLUDE]
    # core first, then the area modules alphabetically (stable tool ordering).
    names.sort(key=lambda n: (n != "core", n))

    specs: list[ToolSpec] = []
    handlers: dict[str, Handler] = {}
    for name in names:
        mod = importlib.import_module(f"{__name__}.{name}")
        for spec in getattr(mod, "SPECS", []):
            specs.append(spec)
        for tool_name, handler in getattr(mod, "HANDLERS", {}).items():
            if tool_name in handlers:
                raise RuntimeError(f"duplicate tool name {tool_name!r} (module {name})")
            handlers[tool_name] = handler
    return specs, handlers


TOOL_SPECS, _HANDLERS = _load()


async def execute_tool(db, ctx, *, agent, task, name: str, args: dict) -> ToolOutcome:
    handler = _HANDLERS.get(name)
    if handler is None:
        return ToolOutcome(observation=f"unknown tool {name}")
    return await handler(db, ctx, agent=agent, task=task, args=args)


__all__ = ["TOOL_SPECS", "execute_tool", "ToolOutcome"]
