"""NativeBackend — the in-house think→act→observe agent loop (the only MVP backend).

Per step: one metered LLM call (through :class:`CostMeter`) may emit tool calls;
each tool call is screened by the governance engine, then executed. The loop ends
on ``report_result``, a parked decision, a tripped breaker, or the step cap.

Tool results are fed back to the model with the proper multi-turn tool_result
protocol: an assistant turn echoing the model's ``tool_use`` blocks (one per
:class:`ToolCall`, preserving ids), followed by a user turn carrying one
``tool_result`` block per executed tool. The structured blocks live behind the
provider-agnostic :mod:`app.providers.base` content-block model, so the loop
stays independent of any vendor's message shape.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, DecisionRequest, Mission, SpendEntry, Task
from app.models.enums import AgentRole, DecisionKind, DecisionStatus, PolicyEffect, TaskStatus
from app.db import set_tenant
from app.providers.base import LLMProvider, Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.runtime import breakers
from app.runtime.context import RuntimeContext
from app.runtime.prompts import AGENT_LOOP_SYSTEM, ROLE_DESCRIPTIONS
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.services import apikeys, reputation
from app.services import governance as gov

# Conservative pre-execution price hint (cents) for governance evaluation only.
# Domain pricing is now quoted dynamically by the registrar at execution time
# (see app.integrations); this hint just lets policies gate the action up front.
_DOMAIN_PRICE_HINT_CENTS = 4000
_COST_HINTS = {"register_domain": _DOMAIN_PRICE_HINT_CENTS}


def _model_for(agent: Agent, provider: LLMProvider) -> str:
    """Agent's explicit preference, else the provider's tier default."""
    if agent.model_pref:
        return agent.model_pref
    tier = "planner" if agent.role is AgentRole.ceo else "cheap"
    return provider.default_models.get(tier, provider.default_models["cheap"])


class NativeBackend:
    async def run(self, ctx: RuntimeContext, agent: Agent, task: Task) -> dict:
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            mission = await db.scalar(
                select(Mission).where(Mission.company_id == task.company_id).limit(1)
            )
            mission_text = mission.generated_summary or mission.raw_text if mission else ""
            resolved = await apikeys.resolve_provider(db, company_id=task.company_id)
        if resolved is None:
            return await self._finish(ctx, task, TaskStatus.failed, {"error": "no API key"})
        provider, api_key = resolved

        system = AGENT_LOOP_SYSTEM.format(
            role_desc=ROLE_DESCRIPTIONS.get(agent.role, ""),
            mission=mission_text,
            goal=task.goal,
        )
        messages: list[Message] = [Message(role="user", content=f"Begin: {task.goal}")]
        model = _model_for(agent, provider)

        for _ in range(settings.max_steps_per_task):
            resp = await ctx.cost_meter.run_llm(
                provider,
                api_key=api_key,
                company_id=task.company_id,
                agent_id=agent.id,
                task_id=task.id,
                model=model,
                system=system,
                messages=messages,
                tools=TOOL_SPECS,
                max_tokens=2048,
            )

            if not resp.tool_calls:
                return await self._finish(
                    ctx, task, TaskStatus.done, {"summary": resp.text[:2000]}
                )

            results: list[ToolResultBlock] = []
            for call in resp.tool_calls:
                verdict = await self._handle_call(ctx, agent, task, call)
                if verdict["terminal"]:
                    return verdict["result"]
                results.append(
                    ToolResultBlock(
                        tool_use_id=call.id,
                        content=verdict["observation"],
                        is_error=verdict.get("is_error", False),
                    )
                )

            # Assistant turn: echo the model's tool_use blocks (ids preserved),
            # prefixed with any leading text the model emitted.
            assistant_blocks: list = []
            if resp.text:
                assistant_blocks.append(TextBlock(text=resp.text))
            assistant_blocks.extend(
                ToolUseBlock(id=c.id, name=c.name, input=c.arguments) for c in resp.tool_calls
            )
            messages.append(Message(role="assistant", content=assistant_blocks))
            # User turn: one tool_result per executed tool, matched by id.
            messages.append(Message(role="user", content=list(results)))

        return await self._finish(ctx, task, TaskStatus.done, {"summary": "step cap reached"})

    async def _handle_call(self, ctx: RuntimeContext, agent: Agent, task: Task, call) -> dict:
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            action = {
                "tool": call.name,
                "agent_role": agent.role.value,
                "amount_cents": _COST_HINTS.get(call.name, call.arguments.get("amount_cents")),
            }
            effect = await gov.evaluate(db, company_id=task.company_id, action=action)

            if effect is PolicyEffect.deny:
                await db.commit()
                return {
                    "terminal": False,
                    "observation": f"DENIED by policy: {call.name}",
                    "is_error": True,
                }

            if effect is PolicyEffect.require_approval:
                db.add(
                    DecisionRequest(
                        company_id=task.company_id,
                        agent_id=agent.id,
                        task_id=task.id,
                        kind=DecisionKind.spend_approval,
                        summary=f"Approve {call.name}({call.arguments})",
                        payload={"tool": call.name, "args": call.arguments},
                        status=DecisionStatus.pending,
                    )
                )
                task_row = await db.get(Task, task.id)
                task_row.status = TaskStatus.waiting_approval
                await db.commit()
                return {
                    "terminal": True,
                    "result": {"status": "waiting_approval", "tool": call.name},
                }

            outcome = await execute_tool(
                db, ctx, agent=agent, task=task, name=call.name, args=call.arguments
            )
            await db.commit()

        if outcome.stop:
            return {
                "terminal": True,
                "result": await self._finish(
                    ctx, task, TaskStatus.done, {"summary": call.arguments.get("summary", "")}
                ),
            }
        if outcome.park:
            return {"terminal": True, "result": {"status": "waiting_approval"}}
        return {"terminal": False, "observation": outcome.observation}

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
