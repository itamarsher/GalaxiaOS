"""ConnectedBackend — delegate a function's execution to an external worker.

RFC 0001 (``docs/rfcs/0001-business-control-plane.md``): an :class:`AgentBackend`
whose ``run`` doesn't execute a think→act loop. It assembles the function's
**mandate** + **initiative** from the Business-Function surface, hands them to a
:class:`WorkerClient` (an external agent runtime — e.g. a managed OpenClaw
Gateway), and closes the initiative through ``business_function.report_result``.

Sibling to :class:`~app.runtime.backends.marketplace.MarketplaceBackend`: the org
chart treats the agent identically (status, cost rollup via report_result's
finalize, transcript teardown, delegated-result propagation) — only *where* the
work runs differs.

This is the **push** posture (Galaxia invokes the worker and awaits its report),
which fits the synchronous orchestrator. The **pull** posture — a worker claiming
initiatives on its own cadence over MCP (``claim_initiative`` / the step-3
lease) — builds on the very same surface and lands separately.

The concrete :class:`WorkerClient` (an OpenClaw HTTP client, the MCP server that
exposes the surface, and per-function auth) is wired in a follow-up; here the
backend is registered against the reserved ``external`` backend type with no worker
attached, so an ``external`` agent fails with a clear "no runtime connected"
message until one is bound. Fully covered by tests with a fake worker.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from app.db import set_tenant
from app.models import Agent, Task
from app.models.enums import TaskStatus
from app.observability import get_logger
from app.runtime.context import RuntimeContext
from app.services import business_function
from app.services import tasks as task_svc

_log = get_logger("abos.connected_backend")


class WorkerReport(BaseModel):
    """What an external worker returns after acting on an initiative."""

    outcome: str  # done | failed | blocked | needs_decision (see business_function)
    output: dict = {}


class WorkerClient(Protocol):
    """An external runtime that executes one initiative and reports the outcome."""

    async def execute(
        self,
        *,
        mandate: business_function.Mandate,
        initiative: business_function.Initiative,
    ) -> WorkerReport: ...


class ConnectedBackend:
    def __init__(self, worker: WorkerClient | None = None) -> None:
        # No worker bound yet => an `external` agent fails clearly rather than
        # silently doing nothing. A follow-up binds a real OpenClaw client here.
        self._worker = worker

    async def run(self, ctx: RuntimeContext, agent: Agent, task: Task) -> dict:
        if self._worker is None:
            return await self._fail(
                ctx,
                task,
                "no external worker runtime is connected for this function yet",
            )

        # Assemble the briefing the worker needs — the same contract any external
        # agent pulls — and the specific initiative it's being handed (this task).
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            mandate = await business_function.get_mandate(
                db, company_id=task.company_id, agent_id=agent.id, redact_for_access=True
            )
            initiative = business_function.Initiative(
                id=task.id,
                function=agent.role.value,
                goal=task.goal,
                status=task.status.value,
                created_at=task.created_at.isoformat(),
                budget=mandate.budget,
            )

        try:
            report = await self._worker.execute(mandate=mandate, initiative=initiative)
        except Exception as exc:  # noqa: BLE001 - a worker fault must fail the task, not the run
            _log.warning("connected worker failed (task=%s): %s", task.id, exc)
            return await self._fail(ctx, task, f"external worker failed: {exc}")

        # Close the initiative through the shared surface — done/failed/blocked
        # finalize; needs_decision parks + escalates. Re-read the resulting status
        # so the orchestrator sees exactly what report_result applied.
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            await business_function.report_result(
                db,
                company_id=task.company_id,
                task_id=task.id,
                outcome=report.outcome,
                output=report.output or {"summary": ""},
                agent_id=agent.id,
            )
            await db.commit()
            row = await db.get(Task, task.id)
            status = row.status.value if row is not None else TaskStatus.done.value
        return {"status": status, "output": report.output}

    async def _fail(self, ctx: RuntimeContext, task: Task, reason: str) -> dict:
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            row = await db.get(Task, task.id)
            if row is None:  # pragma: no cover
                return {"status": TaskStatus.failed.value}
            await task_svc.finalize(
                db, task=row, status=TaskStatus.failed, output={"error": reason}
            )
            await db.commit()
        return {"status": TaskStatus.failed.value, "output": {"error": reason}}
