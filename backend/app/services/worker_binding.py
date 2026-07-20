"""Default worker binding for a newly generated function slot (RFC 0001 §5).

The generated org is a set of **function slots**; each is filled by a worker — an
internal agent, an external agent, or a human. Step 5 makes the *default internal
runtime* configurable so a deployment can ship the **managed OpenClaw Gateway** as
the batteries-included binding: with ``ABOS_DEFAULT_AGENT_BACKEND=external`` (and a
Gateway configured), every generated function auto-binds to the connected runtime
instead of the in-process loop — the "same-day" path §5 describes — while a plain
deployment keeps ``native``.

Two invariants keep this safe:

- **The CEO always runs natively.** It orchestrates the company; its loop stays
  in-process regardless of the default.
- **``external`` only when a Gateway is actually bound.** If the default is set to
  ``external`` but no ``openclaw_base_url`` is configured, we fall back to ``native``
  so a mis-set default can never strand a function with an ``external`` runtime and
  no worker (which would fail its tasks with "no runtime connected").
"""

from __future__ import annotations

from app.config import settings
from app.models.enums import AgentBackendType, AgentRole


def default_backend_for(role: AgentRole) -> AgentBackendType:
    """The runtime a freshly generated agent in ``role`` should bind to."""
    if role is AgentRole.ceo:
        return AgentBackendType.native
    if settings.default_agent_backend == "external" and settings.openclaw_base_url:
        return AgentBackendType.external
    return AgentBackendType.native
