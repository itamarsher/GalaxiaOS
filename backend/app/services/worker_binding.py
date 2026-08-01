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
- **The GLOBAL ``external`` default only takes effect when a Gateway is bound.** If
  ``default_agent_backend=external`` but no ``openclaw_base_url`` is configured, we
  fall back to ``native`` so a mis-set default can never strand a PUSH function with
  no worker (which would fail its tasks with "no runtime connected").

The **coding** function is the deliberate exception: it binds to ``external`` by
default (``delegate_coding_external``) with NO Gateway required, because an external
function with no bound push worker now parks its initiatives for a PULL worker to
claim over the Business-Function MCP instead of failing (``orchestrator.run_task``).
That is how a connected coding runtime (opencode / Claude Code) staffs the
engineering function by default (RFC 0003).
"""

from __future__ import annotations

from app.config import settings
from app.models.enums import AgentBackendType, AgentRole


def default_backend_for(role: AgentRole, function: str | None = None) -> AgentBackendType:
    """The runtime a freshly generated agent should bind to.

    ``function`` is the catalog key of the block this agent staffs (e.g.
    ``"engineering"``), when known — several blocks share the ``custom`` role, so the
    role alone can't identify the coding function.
    """
    if role is AgentRole.ceo:
        return AgentBackendType.native
    # Coding is delegated to an EXTERNAL coding runtime by default (RFC 0003): a
    # connected agent (opencode / Claude Code) pulls the engineering function's
    # initiatives over the Business-Function MCP, instead of the in-process loop
    # writing code it can never compile or run. Safe without a push Gateway — an
    # external function with no bound worker parks its initiatives for a pull worker
    # to claim (``orchestrator.run_task``), so it never strands.
    if function == "engineering" and settings.delegate_coding_external:
        return AgentBackendType.external
    if settings.default_agent_backend == "external" and settings.openclaw_base_url:
        return AgentBackendType.external
    return AgentBackendType.native
