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

from app.config import settings
from app.db import set_tenant
from app.models import Agent, DecisionRequest, Mission, SpendEntry, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    MemoryType,
    PolicyEffect,
    TaskStatus,
)
from app.providers.base import LLMProvider, Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.runtime.context import RuntimeContext
from app.runtime.prompts import AGENT_LOOP_SYSTEM, ROLE_DESCRIPTIONS
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.runtime.tools.base import consume_approval_grant as _consume_approval_grant
from app.services import apikeys, memory, metrics, reputation
from app.services import governance as gov
from app.services.budget import BudgetExceeded

# Model tiers, cheapest -> most capable. Used for reputation-driven escalation.
_MODEL_TIERS = ("cheap", "planner", "strategic")


def _escalate_tier(tier: str, trust: float | None) -> str:
    """Bump a model tier one notch when the agent's trust is low.

    Pure helper (no I/O) so the escalation policy is unit-testable. Returns the
    next tier up when ``settings.reputation_model_escalation`` is on and ``trust``
    is below ``settings.reputation_escalate_below``; otherwise ``tier`` unchanged.
    """
    if not settings.reputation_model_escalation:
        return tier
    if trust is None or trust >= settings.reputation_escalate_below:
        return tier
    try:
        idx = _MODEL_TIERS.index(tier)
    except ValueError:
        return tier
    return _MODEL_TIERS[min(idx + 1, len(_MODEL_TIERS) - 1)]

# Conservative pre-execution price hint (cents) for governance evaluation only.
# Domain pricing is now quoted dynamically by the registrar at execution time
# (see app.integrations); this hint just lets policies gate the action up front.
_DOMAIN_PRICE_HINT_CENTS = 4000
_COST_HINTS = {"register_domain": _DOMAIN_PRICE_HINT_CENTS}


def _summarize_memory(entries) -> str:
    """Render recalled memory entries as a compact ``type: title`` bullet list."""
    if not entries:
        return "No prior learnings recorded yet."
    return "\n".join(f"- {e.type.value}: {e.title}" for e in entries)


def _model_for(agent: Agent, provider: LLMProvider, trust: float | None = None) -> str:
    """Agent's explicit preference, else the provider's tier default.

    When no explicit ``model_pref`` is set, the base tier (planner for the CEO,
    cheap otherwise) may be escalated one notch if the agent's reputation
    ``trust`` is low — give a struggling agent a stronger model.
    """
    if agent.model_pref:
        return agent.model_pref
    tier = "planner" if agent.role is AgentRole.ceo else "cheap"
    tier = _escalate_tier(tier, trust)
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

            # Perceive: recall relevant institutional memory and recent real-world
            # metrics so the loop reasons from what's known, not from a blank slate.
            recalled = await memory.query(
                db,
                company_id=task.company_id,
                text=task.goal,
                limit=settings.memory_recall_limit,
            )
            memory_summary = _summarize_memory(recalled)
            signals = await metrics.latest_signals(
                db, company_id=task.company_id, limit=settings.metrics_recall_limit
            )
            metrics_summary = metrics.summarize_for_prompt(signals)

            # Reputation drives model selection (escalate a struggling agent).
            rep = await reputation.get_or_create(
                db, company_id=task.company_id, agent_id=agent.id
            )
            trust = rep.trust
        if resolved is None:
            return await self._finish(ctx, task, TaskStatus.failed, {"error": "no API key"})
        provider, api_key = resolved

        system = AGENT_LOOP_SYSTEM.format(
            role_desc=ROLE_DESCRIPTIONS.get(agent.role, ""),
            mission=mission_text,
            goal=task.goal,
            memory=memory_summary,
            metrics=metrics_summary,
        )
        messages: list[Message] = [Message(role="user", content=f"Begin: {task.goal}")]
        model = _model_for(agent, provider, trust)

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

            if effect is PolicyEffect.require_approval and not await _consume_approval_grant(
                db, task_id=task.id, tool=call.name
            ):
                # No standing approval for this action — park the task and ask the
                # founder. (If a grant existed, it was just consumed and we fall
                # through to execute, so an approved action isn't re-escalated.)
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

            try:
                outcome = await execute_tool(
                    db, ctx, agent=agent, task=task, name=call.name, args=call.arguments
                )
            except BudgetExceeded as exc:
                # The action would blow the budget. Rather than fail the task
                # outright (the old behaviour: "error": "BudgetExceeded"), treat
                # it like a spend the CEO can't authorise alone and escalate it to
                # the founder. Approving raises the budget ceiling by the shortfall
                # so the action goes through on resume.
                await db.rollback()
                shortfall = max(0, exc.requested_cents - exc.available_cents)
                db.add(
                    DecisionRequest(
                        company_id=task.company_id,
                        agent_id=agent.id,
                        task_id=task.id,
                        kind=DecisionKind.spend_approval,
                        summary=(
                            f"**Over budget — approval needed**\n\n"
                            f"`{call.name}` needs **${exc.requested_cents / 100:.2f}**, "
                            f"but only **${max(0, exc.available_cents) / 100:.2f}** is left "
                            f"in the {exc.scope} budget.\n\n"
                            f"Approve to add **${shortfall / 100:.2f}** of headroom and proceed."
                        ),
                        payload={
                            "tool": call.name,
                            "args": call.arguments,
                            "requested_cents": exc.requested_cents,
                            "available_cents": exc.available_cents,
                            "budget_increase_cents": shortfall,
                        },
                        status=DecisionStatus.pending,
                    )
                )
                task_row = await db.get(Task, task.id)
                if task_row is not None:
                    task_row.status = TaskStatus.waiting_approval
                await db.commit()
                return {
                    "terminal": True,
                    "result": {"status": "waiting_approval", "tool": call.name},
                }
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
        return {
            "terminal": False,
            "observation": outcome.observation,
            "is_error": outcome.is_error,
        }

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

            # Delegation result propagation: when a delegated (child) task
            # completes, persist its outcome to memory so it resurfaces to the
            # parent/CEO via memory recall on a later step. Best-effort.
            if status is TaskStatus.done and row.parent_task_id is not None:
                try:
                    await memory.write(
                        db,
                        company_id=task.company_id,
                        type=MemoryType.result,
                        title=f"Result: {row.goal[:80]}",
                        content=output.get("summary", "") or "(no summary)",
                        source_task_id=task.id,
                    )
                except Exception:  # noqa: BLE001 — propagation must not fail finish
                    pass

            await db.commit()
        return {"status": status.value, "output": output}
