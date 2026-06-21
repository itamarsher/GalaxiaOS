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

import uuid

from sqlalchemy import select

from app.config import settings
from app.db import set_tenant
from app.models import Agent, DecisionRequest, Mission, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    ExternalMessageStatus,
    PolicyEffect,
    TaskStatus,
)
from app.providers.base import LLMProvider, Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.runtime.context import RuntimeContext
from app.runtime.prompts import AGENT_LOOP_SYSTEM, ROLE_DESCRIPTIONS
from app.runtime.tools import TOOL_SPECS, execute_tool
from app.runtime.tools.base import consume_approval_grant as _consume_approval_grant
from app.runtime.transcript import dump_messages, load_messages
from app.services import apikeys, memory, metrics, reputation
from app.services import external_messages as ext
from app.services import governance as gov
from app.services import tasks as task_svc
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
        messages = self._resume_or_seed(task)
        await self._inject_audit_feedback(ctx, task, messages)
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
                return await self._finish_or_audit(
                    ctx, agent, task, {"summary": resp.text[:2000]}
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

            # Checkpoint working memory at the step boundary: the conversation is
            # now a complete, valid resume point (every tool_use has its
            # tool_result), so a restart can pick the task back up here.
            await self._save_transcript(ctx, task, messages)

        return await self._finish_or_audit(ctx, agent, task, {"summary": "step cap reached"})

    def _resume_or_seed(self, task: Task) -> list[Message]:
        """Resume the loop from a persisted checkpoint, else seed a fresh start.

        A task orphaned by a restart is reset to ``queued`` and re-dispatched by
        :mod:`app.jobs.recovery`; if it had checkpointed its conversation we
        replay those turns so it continues where it left off instead of redoing
        work already paid for.
        """
        if settings.persist_task_transcript and task.transcript:
            resumed = load_messages(task.transcript)
            if resumed:
                return resumed
        return [Message(role="user", content=f"Begin: {task.goal}")]

    async def _save_transcript(
        self, ctx: RuntimeContext, task: Task, messages: list[Message]
    ) -> None:
        """Checkpoint the loop's working memory so a restart can resume it.

        Best-effort and called only at step boundaries, so the persisted
        conversation is always a valid resume point — never a half-applied step
        with a dangling ``tool_use``.
        """
        if not settings.persist_task_transcript:
            return
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            row = await db.get(Task, task.id)
            if row is not None:
                row.transcript = dump_messages(messages)
                await db.commit()

    async def _handle_call(self, ctx: RuntimeContext, agent: Agent, task: Task, call) -> dict:
        is_external = ext.is_external_comm(call.name)
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            action = {
                "tool": call.name,
                "agent_role": agent.role.value,
                "amount_cents": _COST_HINTS.get(call.name, call.arguments.get("amount_cents")),
                # Lets a single policy gate every outbound communication channel.
                "is_external": is_external,
            }
            effect = await gov.evaluate(db, company_id=task.company_id, action=action)

            if effect is PolicyEffect.deny:
                # Index the blocked attempt so the founder can see what the agent
                # tried to send (and which policy stopped it).
                if is_external:
                    await ext.record(
                        db,
                        company_id=task.company_id,
                        agent_id=agent.id,
                        task_id=task.id,
                        tool=call.name,
                        args=call.arguments,
                        status=ExternalMessageStatus.blocked,
                        detail="Denied by policy.",
                    )
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
                # Outbound messages get a dedicated kind + a readable summary so the
                # founder can weigh (and discuss) the actual content, and the parked
                # message is indexed and linked to its decision.
                decision = DecisionRequest(
                    company_id=task.company_id,
                    agent_id=agent.id,
                    task_id=task.id,
                    kind=DecisionKind.external_comm if is_external else DecisionKind.spend_approval,
                    summary=(
                        ext.summarize(call.name, call.arguments)
                        if is_external
                        else f"Approve {call.name}({call.arguments})"
                    ),
                    payload={"tool": call.name, "args": call.arguments},
                    status=DecisionStatus.pending,
                )
                db.add(decision)
                if is_external:
                    await db.flush()
                    await ext.record(
                        db,
                        company_id=task.company_id,
                        agent_id=agent.id,
                        task_id=task.id,
                        tool=call.name,
                        args=call.arguments,
                        status=ExternalMessageStatus.pending_approval,
                        decision_id=decision.id,
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

            # Index the outbound communication's outcome. On an approved resume this
            # flips the parked ``pending_approval`` row to its terminal state; on the
            # unguarded path it inserts a fresh ``sent``/``failed`` record.
            if is_external:
                await ext.finalize(
                    db,
                    company_id=task.company_id,
                    agent_id=agent.id,
                    task_id=task.id,
                    tool=call.name,
                    args=call.arguments,
                    sent=not outcome.is_error,
                    detail=outcome.observation,
                )
            await db.commit()

        if outcome.stop:
            return {
                "terminal": True,
                "result": await self._finish_or_audit(
                    ctx, agent, task, {"summary": call.arguments.get("summary", "")}
                ),
            }
        if outcome.park:
            return {"terminal": True, "result": {"status": "waiting_approval"}}
        return {
            "terminal": False,
            "observation": outcome.observation,
            "is_error": outcome.is_error,
        }

    async def _finish_or_audit(
        self, ctx: RuntimeContext, agent: Agent, task: Task, output: dict
    ) -> dict:
        """A successful result either lands in ``auditing`` for CEO review or, when
        no audit applies, finishes as ``done`` straight away.

        Only results the CEO delegated are audited (see ``task_svc.should_audit``);
        everything else — the CEO's own work, sub-tasks the CEO didn't dispatch, or
        a task that has already exhausted its reopen budget — finishes normally.
        """
        audit_task_id: uuid.UUID | None = None
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            if await task_svc.should_audit(db, agent=agent, task=task):
                audit_task_id = await task_svc.begin_auditing(
                    db, child_id=task.id, output=output
                )
                if audit_task_id is not None:
                    await db.commit()
        if audit_task_id is not None:
            await ctx.enqueue_task(audit_task_id)
            return {"status": TaskStatus.auditing.value, "output": output}
        return await self._finish(ctx, task, TaskStatus.done, output)

    async def _finish(
        self, ctx: RuntimeContext, task: Task, status: TaskStatus, output: dict
    ) -> dict:
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            row = await db.get(Task, task.id)
            if row is None:  # pragma: no cover
                return {"status": status.value}
            await task_svc.finalize(db, task=row, status=status, output=output)
            # Safety net: if this is a CEO audit task finishing without the CEO
            # having resolved its target, don't strand the target in ``auditing``
            # — accept it so the result still propagates and the run can wind down.
            await self._resolve_dangling_audit(db, row)
            await db.commit()
        return {"status": status.value, "output": output}

    async def _resolve_dangling_audit(self, db, task: Task) -> None:
        info = task.input or {}
        target_id = info.get("audit_target_task_id")
        if not target_id:
            return
        target = await db.get(Task, uuid.UUID(str(target_id)))
        if target is not None and target.status is TaskStatus.auditing:
            # A result audit settles as ``done``; a failure review the CEO never
            # resolved settles as ``failed`` (don't silently auto-retry it).
            outcome = (
                TaskStatus.failed
                if info.get("audit_target_outcome") == "failed"
                else TaskStatus.done
            )
            await task_svc.finalize(
                db, task=target, status=outcome, output=target.output or {"summary": ""}
            )

    async def _inject_audit_feedback(
        self, ctx: RuntimeContext, task: Task, messages: list[Message]
    ) -> None:
        """When the CEO reopened this task, surface its comments as the agent's
        first instruction after its prior chat history, then consume them so the
        feedback is injected only once."""
        feedback = (task.input or {}).get("audit_feedback")
        if not feedback:
            return
        note = TextBlock(
            text=(
                "The CEO audited your previous result and REOPENED this task. "
                "Address this feedback before reporting again:\n" + str(feedback)
            )
        )
        # Keep user/assistant turns alternating: merge into a trailing user turn
        # rather than appending a second consecutive user message.
        if messages and messages[-1].role == "user":
            content = messages[-1].content
            if isinstance(content, list):
                content.append(note)
            else:
                messages[-1] = Message(
                    role="user", content=[TextBlock(text=str(content)), note]
                )
        else:
            messages.append(Message(role="user", content=[note]))

        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            row = await db.get(Task, task.id)
            if row is not None and row.input and "audit_feedback" in row.input:
                row.input = {k: v for k, v in row.input.items() if k != "audit_feedback"}
                await db.commit()
        if task.input:
            task.input = {k: v for k, v in task.input.items() if k != "audit_feedback"}
