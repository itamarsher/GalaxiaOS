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
from app.models import Agent, Company, DecisionRequest, Mission, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    ExternalMessageStatus,
    PolicyEffect,
    TaskStatus,
)
from app.providers.base import LLMProvider, Message, TextBlock, ToolResultBlock, ToolUseBlock
from app.runtime import critic as critic_svc
from app.runtime import skills as skills_lib
from app.runtime.context import RuntimeContext
from app.runtime.prompts import ROLE_DESCRIPTIONS, render_agent_system
from app.runtime.tools import (
    CORE_TOOL_NAMES,
    execute_tool,
    resolve_tool_names,
    specs_for,
)
from app.runtime.tools.base import ToolOutcome, clip
from app.runtime.tools.base import consume_approval_grant as _consume_approval_grant
from app.runtime.tools.base import consume_rejection_grant as _consume_rejection_grant
from app.runtime.transcript import dump_messages, load_messages, sanitize_messages, transcript_lines
from app.services import apikeys, chat, memory, metrics, reputation
from app.services import external_messages as ext
from app.services import governance as gov
from app.services import integrations as integrations_svc
from app.services import mcp as mcp_svc
from app.services import objectives as objectives_svc
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


def _names_from_use_tool_call(arguments: dict | None) -> list[str]:
    """The valid tool names a ``use_tool`` call asked to load."""
    raw = (arguments or {}).get("names")
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    loadable, _unknown = resolve_tool_names(raw)
    return loadable


def _active_tools_from_messages(messages: list[Message]) -> set[str]:
    """Reconstruct a task's live tool set from its transcript.

    The active set is the core tools plus everything the agent hot-loaded with
    ``use_tool`` so far. Replaying it from the persisted conversation means a task
    resumed in a fresh process keeps the tools it had discovered, with no extra
    state to persist. (Within a single run the set is kept in memory and only grows,
    so mid-run compaction never drops a loaded tool.)
    """
    active = set(CORE_TOOL_NAMES)
    for msg in messages:
        if msg.role != "assistant" or not isinstance(msg.content, list):
            continue
        for block in msg.content:
            if isinstance(block, ToolUseBlock) and block.name == "use_tool":
                active.update(_names_from_use_tool_call(block.input))
    return active


def _absorb_use_tool(active: set[str], tool_calls) -> None:
    """Grow ``active`` with any tools the model just asked to load this step."""
    for call in tool_calls:
        if call.name == "use_tool":
            active.update(_names_from_use_tool_call(call.arguments))


class NativeBackend:
    async def run(self, ctx: RuntimeContext, agent: Agent, task: Task) -> dict:
        # A task that parked to wait for a teammate's (or the founder's) reply must
        # resume back INTO waiting until that reply actually arrives — not free-run
        # the model. The pending ChatWait is the durable source of truth for "still
        # blocked"; the checkpointed transcript deliberately never records the wait
        # (the loop parks before the step is persisted, so the idempotent re-issue
        # can re-deliver the reply on the real wake-up). Without this guard a task
        # resumed while its wait is still pending would replay a history that
        # predates the wait and could act as if the work were done — e.g. message
        # the founder with a result instead of continuing to wait. A satisfied wait
        # (the reply landed) is NOT pending, so the normal resume proceeds.
        if await self._still_waiting_for_reply(ctx, task):
            return {"status": TaskStatus.waiting_approval.value}

        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            mission = await db.scalar(
                select(Mission).where(Mission.company_id == task.company_id).limit(1)
            )
            mission_text = mission.generated_summary or mission.raw_text if mission else ""
            # The company's objectives, numbered, so the agent can tag a dispatched
            # initiative with the objective it advances (dispatch_task `objective`).
            objectives_block = objectives_svc.objectives_prompt_block(
                await objectives_svc.ordered_objectives(db, task.company_id)
            )
            # The company's global operating playbook (best practices + emerging
            # directives) is injected into every agent's launch prompt, so editing it
            # updates the whole fleet on their next run.
            company_playbook = await db.scalar(
                select(Company.playbook).where(Company.id == task.company_id)
            )
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
            rep = await reputation.get_or_create(db, company_id=task.company_id, agent_id=agent.id)
            trust = rep.trust

            # Connected MCP servers contribute extra, company-specific tools. Built
            # per-run (they are per-company and may change between runs); routing
            # maps each prefixed tool name back to (server_id, remote_tool_name).
            mcp_specs, mcp_routing = await mcp_svc.tool_specs_for_company(
                db, company_id=task.company_id
            )

            # Whether the company's file store (Drive) is actually connected, so the
            # prompt tells the agent the truth about `save_file` rather than always
            # claiming a file store exists. Resolved in this same tenant-scoped
            # session, so it matches exactly what the file tools will see.
            file_store_connected = (
                await integrations_svc.resolve_file_provider(db, company_id=task.company_id)
            ) is not None
        if resolved is None:
            return await self._finish(ctx, task, TaskStatus.failed, {"error": "no API key"})
        provider, api_key = resolved

        system = render_agent_system(
            role_desc=ROLE_DESCRIPTIONS.get(agent.role, ""),
            agent_directive=agent.system_prompt,
            playbook=company_playbook,
            mission=mission_text,
            goal=task.goal,
            memory=memory_summary,
            metrics=metrics_summary,
            skills=skills_lib.index_for_role(agent.role.value),
            objectives=objectives_block,
            file_store_connected=file_store_connected,
        )
        messages = self._resume_or_seed(task)
        await self._inject_resume_notes(ctx, task, messages)
        # Tool discovery: a task starts with only the core toolset and grows as the
        # agent hot-loads tools with `use_tool`. Seed the live set from the transcript
        # so a task resumed in a fresh process keeps the tools it already discovered.
        # MCP tools (per-company, few) stay always-on alongside the core set.
        active_tools = _active_tools_from_messages(messages)
        # Watermark for the "catch up on new chat" nudge, carried across steps so
        # each new batch of channel activity is surfaced once (on resume and while
        # running). Seeded from the persisted value and advanced as we nudge.
        chat_seen = task.chat_seen_at
        model = _model_for(agent, provider, trust)
        # Size the per-step output budget to the model's real ceiling (bounded by
        # ``max_response_tokens``) rather than a fixed small cap, so a large
        # deliverable packed into one ``report_result`` summary isn't truncated
        # mid-output. The provider transparently streams when this exceeds its
        # non-streaming size guard (see ``AnthropicProvider.complete``).
        max_tokens = min(provider.max_output_tokens(model), settings.max_response_tokens)

        for _ in range(settings.max_steps_per_task):
            messages = await self._maybe_compact(ctx, task, provider, api_key, model, messages)
            chat_seen = await self._maybe_nudge_chat(ctx, agent, task, messages, chat_seen)
            # Only the currently-loaded tools are offered this step; the list grows as
            # the agent discovers and hot-loads more (see `_absorb_use_tool` below).
            tools = specs_for(active_tools) + mcp_specs
            resp = await ctx.cost_meter.run_llm(
                provider,
                api_key=api_key,
                company_id=task.company_id,
                agent_id=agent.id,
                task_id=task.id,
                model=model,
                system=system,
                messages=messages,
                tools=tools,
                max_tokens=max_tokens,
            )

            if not resp.tool_calls:
                return await self._finish_or_audit(
                    ctx,
                    agent,
                    task,
                    {"summary": clip(resp.text, settings.max_result_summary_chars)},
                )

            # Hot-load any tools the agent asked for, so they're offered next step.
            _absorb_use_tool(active_tools, resp.tool_calls)

            results: list[ToolResultBlock] = []
            for call in resp.tool_calls:
                verdict = await self._handle_call(ctx, agent, task, call, mcp_routing)
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

    async def _still_waiting_for_reply(self, ctx: RuntimeContext, task: Task) -> bool:
        """Re-park a resumed task that still holds a pending reply-wait.

        Returns ``True`` (and flips the task back to ``waiting_approval``) when a
        pending :class:`~app.models.ChatWait` is outstanding — the task was woken but
        the reply it is blocked on has not arrived, so it must keep waiting rather
        than run the loop. Returns ``False`` for a task with no pending wait (a fresh
        task, or one whose wait was satisfied by an arriving reply), letting the
        normal loop proceed.
        """
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            wait = await chat.pending_reply_wait_for_task(db, task_id=task.id)
            if wait is None:
                return False
            row = await db.get(Task, task.id)
            if row is not None:
                row.status = TaskStatus.waiting_approval
                await db.commit()
        task.status = TaskStatus.waiting_approval  # keep the in-memory copy consistent
        return True

    def _resume_or_seed(self, task: Task) -> list[Message]:
        """Resume the loop from a persisted checkpoint, else seed a fresh start.

        A task orphaned by a restart is reset to ``queued`` and re-dispatched by
        :mod:`app.jobs.recovery`; if it had checkpointed its conversation we
        replay those turns so it continues where it left off instead of redoing
        work already paid for.
        """
        if settings.persist_task_transcript and task.transcript:
            # Repair any tool_use left dangling by an interrupted step before
            # replaying, so the first resumed provider call can't fail on a
            # malformed history (see ``sanitize_messages``).
            resumed = sanitize_messages(load_messages(task.transcript))
            # Invariant: the message history carries only the conversation
            # (user/assistant turns). The system prompt is passed out-of-band on
            # every call (``system=`` — see the providers) and rebuilt fresh each
            # run, so it must never live in the replayed history — that would
            # duplicate it into the context window and confuse the agent. Drop any
            # stray non-conversation turn defensively.
            resumed = [m for m in resumed if m.role in ("user", "assistant")]
            if resumed:
                return resumed
        return [Message(role="user", content=f"Begin: {task.goal}")]

    @staticmethod
    def _safe_compaction_split(messages: list[Message], keep: int) -> int:
        """Index at which to cut history for compaction, or 0 to not compact.

        The tail (kept verbatim) must begin with an *assistant* turn so the
        synthesized recap — a single ``user`` turn — alternates correctly, and so
        the cut never lands between an assistant ``tool_use`` and its ``tool_result``
        (those results live in the tail with their call). Searches from the desired
        keep boundary backward for the nearest assistant turn.
        """
        n = len(messages)
        target = max(1, n - keep)
        for idx in range(target, 0, -1):
            if messages[idx].role == "assistant":
                return idx
        return 0

    async def _maybe_compact(
        self,
        ctx: RuntimeContext,
        task: Task,
        provider: LLMProvider,
        api_key: str,
        model: str,
        messages: list[Message],
    ) -> list[Message]:
        """Summarize older turns into one recap when the conversation grows long.

        Keeps long autonomous runs inside the context window and cheaper per step:
        once the loop exceeds ``compaction_trigger_messages`` turns we replace the
        older prefix with a compact ``user`` recap and keep the most recent turns
        verbatim. No-op (returns ``messages`` unchanged) when disabled, short, or
        when no safe split exists.
        """
        if not settings.context_compaction_enabled:
            return messages
        if len(messages) <= settings.compaction_trigger_messages:
            return messages
        split = self._safe_compaction_split(messages, settings.compaction_keep_recent_messages)
        if split <= 1:
            return messages
        head, tail = messages[:split], messages[split:]
        blob = "\n".join(transcript_lines(dump_messages(head), limit=0))
        if not blob.strip():
            return messages
        resp = await ctx.cost_meter.run_llm(
            provider,
            api_key=api_key,
            company_id=task.company_id,
            agent_id=task.agent_id,
            task_id=task.id,
            model=provider.default_models.get("cheap", model),
            system=(
                "You compact an AI agent's working log. Summarize the earlier part of "
                "this task session into a dense recap the agent can rely on to continue: "
                "preserve decisions made, tools used and their key results, facts learned, "
                "open threads, and anything still in progress. Be specific and terse; omit "
                "chit-chat. Output plain text, no preamble."
            ),
            messages=[Message(role="user", content=blob)],
            max_tokens=700,
        )
        recap = Message(
            role="user",
            content=(
                "Recap of earlier work on this task (older turns were compacted to save "
                "context — treat this as established background):\n" + resp.text
            ),
        )
        compacted = [recap, *tail]
        await self._save_transcript(ctx, task, compacted)
        return compacted

    @staticmethod
    def _append_user_note(messages: list[Message], text: str) -> None:
        """Surface a transient note to the agent on its next turn.

        Attached to the trailing ``user`` turn (after any tool_result blocks) so the
        history keeps alternating roles cleanly; falls back to a fresh ``user`` turn
        only if the last turn isn't a user one (shouldn't happen at a step boundary).
        """
        if messages and messages[-1].role == "user":
            last = messages[-1]
            if isinstance(last.content, str):
                last.content = f"{last.content}\n\n{text}"
            else:
                last.content = [*last.content, TextBlock(text=text)]
        else:
            messages.append(Message(role="user", content=text))

    async def _maybe_nudge_chat(
        self,
        ctx: RuntimeContext,
        agent: Agent,
        task: Task,
        messages: list[Message],
        chat_seen,
    ):
        """Nudge the agent to catch up on new chat in its channels, once per batch.

        Runs at every step boundary, so it fires both when a parked task resumes
        (messages that arrived while it was away) and while a task is actively
        running (a teammate posts mid-task). The per-task watermark advances each
        time so the same activity isn't surfaced twice; it returns the new watermark
        for the caller to carry into the next step.
        """
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            summary, newest = await chat.chat_activity_for_agent(
                db, company_id=task.company_id, agent_id=agent.id, since=chat_seen
            )
            if newest is not None and newest != chat_seen:
                row = await db.get(Task, task.id)
                if row is not None:
                    row.chat_seen_at = newest
                    await db.commit()
                chat_seen = newest
        if summary:
            self._append_user_note(messages, summary)
        return chat_seen

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

    async def _handle_call(
        self, ctx: RuntimeContext, agent: Agent, task: Task, call, mcp_routing: dict | None = None
    ) -> dict:
        is_external = ext.is_external_comm(call.name)
        is_mcp = bool(mcp_routing) and call.name in mcp_routing
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            action = {
                "tool": call.name,
                "agent_role": agent.role.value,
                "amount_cents": _COST_HINTS.get(call.name, call.arguments.get("amount_cents")),
                # External comms and MCP tools both reach outside ABOS, so a single
                # external-sharing policy can gate either.
                "is_external": is_external or is_mcp,
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
                # The founder may already have DECLINED this exact action (the task
                # resumes on a rejection so it can adapt). Don't re-escalate the same
                # call — tell the agent it was declined so it takes another path.
                rejected = await _consume_rejection_grant(
                    db, task_id=task.id, tool=call.name, args=call.arguments
                )
                if rejected is not None:
                    await db.commit()
                    reason = (rejected.payload or {}).get("founder_note")
                    return {
                        "terminal": False,
                        "observation": (
                            f"The founder DECLINED {call.name} — do NOT retry it as-is."
                            + (f' Their reason: "{reason}".' if reason else "")
                            + " Take a different approach or ask them a follow-up."
                        ),
                        "is_error": True,
                    }
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
                await db.flush()
                # Surface the gated action in the agent↔founder DM, marked waiting.
                await chat.attach_decision_dm(db, decision=decision)
                if is_external:
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
                if is_mcp:
                    outcome = await self._call_mcp(db, task, call, mcp_routing)
                else:
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
                decision = DecisionRequest(
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
                db.add(decision)
                await db.flush()
                await chat.attach_decision_dm(db, decision=decision)
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

    async def _call_mcp(self, db, task: Task, call, mcp_routing: dict) -> ToolOutcome:
        """Invoke a connected MCP server's tool, honestly surfacing any failure.

        Consistent with the rest of the platform: an unreachable or erroring server
        returns a tool error the agent must deal with — never a fabricated success.
        """
        route = mcp_routing[call.name]
        try:
            text = await mcp_svc.call_tool(
                db,
                company_id=task.company_id,
                server_id=route["server_id"],
                remote_tool=route["remote_tool"],
                arguments=call.arguments,
            )
        except mcp_svc.McpError as exc:
            return ToolOutcome(
                observation=f"MCP tool {call.name} failed: {exc}. NOTHING happened — do not assume a result.",
                is_error=True,
            )
        return ToolOutcome(observation=clip(text, 4000))

    async def _finish_or_audit(
        self, ctx: RuntimeContext, agent: Agent, task: Task, output: dict
    ) -> dict:
        """A successful result either lands in ``auditing`` for CEO review or, when
        no audit applies, finishes as ``done`` straight away.

        Only results the CEO delegated are audited (see ``task_svc.should_audit``);
        everything else — the CEO's own work, sub-tasks the CEO didn't dispatch, or
        a task that has already exhausted its reopen budget — finishes normally.

        Before either path, an INDEPENDENT devil's-advocate critic reviews the
        result (see :func:`_maybe_critique`); if it wants changes the task is
        re-queued with the critique injected, and this returns without finishing.
        """
        if await self._maybe_critique(ctx, agent, task, output):
            return {"status": TaskStatus.queued.value, "output": output}

        audit_task_id: uuid.UUID | None = None
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            if await task_svc.should_audit(db, agent=agent, task=task):
                audit_task_id = await task_svc.begin_auditing(db, child_id=task.id, output=output)
                if audit_task_id is not None:
                    await db.commit()
        if audit_task_id is not None:
            await ctx.enqueue_task(audit_task_id)
            return {"status": TaskStatus.auditing.value, "output": output}
        return await self._finish(ctx, task, TaskStatus.done, output)

    async def _maybe_critique(
        self, ctx: RuntimeContext, agent: Agent, task: Task, output: dict
    ) -> bool:
        """Independent devil's-advocate review of the result before it counts as done.

        A critic (a separate metered LLM call, no access to this agent's reasoning)
        pushes back on every agent's work. If it finds a real problem and the round
        cap isn't hit, the task is re-queued with the critique injected as feedback —
        the same iterate-until-satisfied loop the CEO audit uses, but universal and
        self-service. Returns ``True`` when it re-queued the task (caller stops).

        Review and its own review tasks (CEO audits, failure reviews) are skipped so
        the critic doesn't recurse or second-guess the overseer.
        """
        if not settings.critic_enabled:
            return False
        info = task.input or {}
        if info.get("audit_target_task_id") or info.get("failure_review"):
            return False
        rounds = int(info.get("critic_rounds", 0))
        if rounds >= settings.critic_max_rounds:
            return False
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            verdict = await critic_svc.review_output(
                db, ctx, company_id=task.company_id, agent=agent, task=task, output=output
            )
            if verdict is None or verdict.approved:
                return False
            row = await db.get(Task, task.id)
            if row is None:  # pragma: no cover - defensive
                return False
            new_input = dict(row.input or {})
            new_input["critic_feedback"] = verdict.feedback()
            new_input["critic_rounds"] = rounds + 1
            row.input = new_input
            row.status = TaskStatus.queued  # re-run with the feedback; transcript is kept
            await db.commit()
        await ctx.enqueue_task(task.id)
        return True

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

    #: Notes stored on ``task.input`` that must be surfaced to the agent on resume
    #: (and consumed once): the CEO's audit comments, the independent critic's
    #: devil's-advocate notes, and a founder-acknowledgment directive when the
    #: founder just resolved this task's escalation. Each maps to the framing shown
    #: to the agent (an empty framing means the stored value is already a full
    #: instruction — see ``founder_ack``, built in ``app.api.decisions``).
    _FEEDBACK_KEYS: tuple[tuple[str, str], ...] = (
        (
            "audit_feedback",
            "The CEO audited your previous result and REOPENED this task. "
            "Address this feedback before reporting again:\n",
        ),
        (
            "critic_feedback",
            "An independent critic reviewed your previous result and was NOT satisfied. "
            "Treat this as a rewrite: address every point before reporting again:\n",
        ),
        ("founder_ack", ""),
    )

    async def _inject_resume_notes(
        self, ctx: RuntimeContext, task: Task, messages: list[Message]
    ) -> None:
        """Surface any pending resume notes (CEO audit, the independent critic, or a
        founder-acknowledgment directive) as the agent's first instruction after its
        prior history, then consume them so each note is injected only once."""
        info = task.input or {}
        notes = [
            TextBlock(text=header + str(info[key]))
            for key, header in self._FEEDBACK_KEYS
            if info.get(key)
        ]
        if not notes:
            return
        # Keep user/assistant turns alternating: merge into a trailing user turn
        # rather than appending a second consecutive user message.
        if messages and messages[-1].role == "user":
            content = messages[-1].content
            if isinstance(content, list):
                content.extend(notes)
            else:
                messages[-1] = Message(
                    role="user", content=[TextBlock(text=str(content)), *notes]
                )
        else:
            messages.append(Message(role="user", content=list(notes)))

        consumed = {key for key, _ in self._FEEDBACK_KEYS}
        async with ctx.session_factory() as db:
            await set_tenant(db, task.company_id)
            row = await db.get(Task, task.id)
            if row is not None and row.input and consumed & set(row.input):
                row.input = {k: v for k, v in row.input.items() if k not in consumed}
                await db.commit()
        if task.input:
            task.input = {k: v for k, v in task.input.items() if k not in consumed}
