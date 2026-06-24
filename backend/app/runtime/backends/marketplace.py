"""MarketplaceBackend — runs a *hired* agent from the marketplace catalog.

At MVP execution is simulated (no real third-party call): the backend charges
the agent's flat ``invocation_price_cents`` per task through the CostMeter as an
``agent_invocation`` spend, records a memory entry describing the engagement, and
finalises the task exactly like :class:`NativeBackend` (status + cost rollup +
reputation). The point is that the marketplace seam is *functional* — spend is
metered and the org chart treats hired agents identically — while the remote
execution itself remains a stub.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.db import set_tenant
from app.models import Agent, SpendEntry, Task
from app.models.enums import MemoryType, TaskStatus
from app.runtime.context import RuntimeContext
from app.services import memory, reputation


class MarketplaceBackend:
    async def run(self, ctx: RuntimeContext, agent: Agent, task: Task) -> dict:
        price = agent.invocation_price_cents or 0
        if price > 0:
            await ctx.cost_meter.charge_agent_invocation(
                company_id=task.company_id,
                agent_id=agent.id,
                task_id=task.id,
                amount_cents=price,
                vendor="marketplace",
                sku=str(agent.marketplace_listing_id) if agent.marketplace_listing_id else None,
                external_ref=str(agent.marketplace_listing_id)
                if agent.marketplace_listing_id
                else None,
                description=f"Marketplace invocation: {agent.name}",
                payload={"goal": task.goal, "role": agent.role.value},
            )

        result = f"Hired agent '{agent.name}' ({agent.role.value}) completed: {task.goal}"

        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            await memory.write(
                db,
                company_id=task.company_id,
                type=MemoryType.result,
                title=f"Marketplace agent {agent.name} delivered",
                content=result,
                source_task_id=task.id,
                structured={
                    "backend": "marketplace",
                    "listing_id": str(agent.marketplace_listing_id)
                    if agent.marketplace_listing_id
                    else None,
                    "invocation_price_cents": price,
                },
            )
            await db.commit()

        return await self._finish(
            ctx, task, TaskStatus.done, {"summary": result, "backend": "marketplace"}
        )

    async def _finish(
        self, ctx: RuntimeContext, task: Task, status: TaskStatus, output: dict
    ) -> dict:
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            row = await db.get(Task, task.id)
            if row is None:  # pragma: no cover
                return {"status": status.value}
            row.status = status
            row.output = output
            cost = await db.scalar(
                select(func.coalesce(func.sum(SpendEntry.amount_cents), 0)).where(
                    SpendEntry.task_id == task.id
                )
            )
            row.cost_cents = int(cost or 0)
            await reputation.record_task_outcome(
                db,
                company_id=task.company_id,
                agent_id=task.agent_id,
                success=status is TaskStatus.done,
                blocked=status is TaskStatus.blocked,
                cost_cents=row.cost_cents,
            )
            await db.commit()
        return {"status": status.value, "output": output}
