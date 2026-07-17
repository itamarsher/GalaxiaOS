"""Agent execution backends — the second decoupling seam.

``AgentBackend`` decides *how* an agent runs, independent of *which model* it
uses (that's :class:`~app.providers.base.LLMProvider`). The orchestrator
dispatches through this Protocol and never assumes the in-house loop, so a
future hired/marketplace agent plugs in here without touching the orchestrator.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.models import Agent, Task
from app.runtime.backends.connected import ConnectedBackend
from app.runtime.backends.marketplace import MarketplaceBackend
from app.runtime.backends.native import NativeBackend
from app.runtime.context import RuntimeContext


@runtime_checkable
class AgentBackend(Protocol):
    async def run(self, ctx: RuntimeContext, agent: Agent, task: Task) -> dict: ...


# Backend registry keyed by Agent.backend_type. "marketplace" runs hired agents
# (execution simulated, spend metered); "external" delegates to a connected
# external worker via the Business-Function surface (RFC 0001) — registered with
# no worker bound yet, so an `external` agent fails clearly until one is wired.
_BACKENDS: dict[str, AgentBackend] = {
    "native": NativeBackend(),
    "marketplace": MarketplaceBackend(),
    "external": ConnectedBackend(),
}


def get_backend(backend_type: str) -> AgentBackend:
    backend = _BACKENDS.get(backend_type)
    if backend is None:
        raise NotImplementedError(
            f"Agent backend {backend_type!r} is not available yet."
        )
    return backend
