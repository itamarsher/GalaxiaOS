"""Shared types for the agent tool registry.

Tools live in per-area modules in this package (``core``, ``sales``,
``marketing``, ``ops``, ``finance``, ``legal``). Each module exposes a
``SPECS: list[ToolSpec]`` and a ``HANDLERS: dict[str, Handler]``; the package
``__init__`` auto-discovers them, so adding a tool is just dropping a function
into the right module — no central registry edits.

Every handler has the same signature::

    async def handler(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome

and tools remain the ONLY way agents affect the world. Tools with real-money
side effects must route their charge through ``ctx.cost_meter`` (same chokepoint
as LLM calls) and put the spend amount in ``args["amount_cents"]`` so governance
and the spend breaker gate them up front.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ToolOutcome:
    observation: str
    stop: bool = False  # report_result -> finish the task
    park: bool = False  # request_decision -> wait for founder
    is_error: bool = False  # surfaced as a tool_result error block to the model


#: Every tool handler is an async callable returning a :class:`ToolOutcome`.
Handler = Callable[..., Awaitable[ToolOutcome]]
__all__ = ["ToolOutcome", "Handler", "Any"]
