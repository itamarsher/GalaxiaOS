"""Chat tools: how agents talk to each other and the founder.

Agents collaborate here the way a human team would in Slack: 1:1 direct messages
(``message_teammate``) and named channels for big cross-agent initiatives
(``start_chat_channel`` / ``send_chat_message``), plus ``list_chat_channels`` and
``read_chat_channel`` to catch up.

The standout capability is **waiting for a reply**. Any send accepts
``wait_for_reply``; when set, the agent's task parks (exactly like a founder
decision) until another participant — an agent or the founder — answers, then
resumes with the reply delivered straight into the agent's context. This is what
makes cross-agent collaboration synchronous when it needs to be: a Growth agent
can ask Research a question and *wait* for the answer instead of guessing.

The resume is idempotent (the chat analog of a one-shot approval grant): on the
re-run after a reply arrives, the same send call finds its now-satisfied
:class:`ChatWait`, delivers the reply, and does NOT re-post the original message.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Agent, ChatWait, Task
from app.models.enums import AgentRole, AgentStatus, ChatWaitStatus, TaskStatus
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome, clip
from app.services import chat

#: Cap on rendered chat output handed back to an agent.
_MAX_CHARS = 6000
#: How the founder is addressed in the DM tool.
_FOUNDER = "founder"

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="list_chat_channels",
        description=(
            "List the chat channels and direct-message threads in the company — "
            "their purpose, members, and most recent message — so you can find the "
            "right place to collaborate or catch up before posting."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="start_chat_channel",
        description=(
            "Open a new chat channel for a big initiative that needs several agents "
            "(and the founder) working together. Use this when a piece of work spans "
            "roles — give it a clear name and purpose and list the agent roles to "
            "include. The founder is always a member. Returns the channel so you can "
            "post to it with send_chat_message."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short channel name, e.g. 'q3-launch'."},
                "purpose": {
                    "type": "string",
                    "description": "What this channel coordinates (the initiative).",
                },
                "members": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Agent roles to add (e.g. ['growth','research','finance']). "
                        "You and the founder are added automatically."
                    ),
                },
            },
            "required": ["name"],
        },
    ),
    ToolSpec(
        name="read_chat_channel",
        description="Read the recent messages in a chat channel by name.",
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "The channel name."},
            },
            "required": ["channel"],
        },
    ),
    ToolSpec(
        name="send_chat_message",
        description=(
            "Post a message to a chat channel by name. Set wait_for_reply=true to "
            "PAUSE your task until another participant (an agent or the founder) "
            "replies — their reply comes back to you so you can continue with it. "
            "Use waiting when you genuinely need an answer before proceeding; "
            "otherwise leave it false and check back later with read_chat_channel."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "channel": {"type": "string", "description": "The channel name."},
                "message": {"type": "string"},
                "wait_for_reply": {
                    "type": "boolean",
                    "description": "Pause this task until someone replies (default false).",
                },
            },
            "required": ["channel", "message"],
        },
    ),
    ToolSpec(
        name="message_teammate",
        description=(
            "Send a direct (1:1) message to another agent by role or name, or to the "
            "founder (use 'founder'). Opens or reuses a private thread between the two "
            "of you. Set wait_for_reply=true to pause your task until they reply — "
            "their answer comes back to you. Use this for a quick question to one "
            "teammate; use a channel for cross-team initiatives."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient: an agent role ('research'), an agent name, or 'founder'.",
                },
                "message": {"type": "string"},
                "wait_for_reply": {
                    "type": "boolean",
                    "description": "Pause this task until they reply (default false).",
                },
            },
            "required": ["to", "message"],
        },
    ),
]


async def _active_agent_for_role(db, *, company_id, role: AgentRole) -> Agent | None:
    return await db.scalar(
        select(Agent)
        .where(
            Agent.company_id == company_id,
            Agent.role == role,
            Agent.status == AgentStatus.active,
        )
        .order_by(Agent.created_at)
        .limit(1)
    )


async def _resolve_member_ids(db, *, company_id, roles: list) -> list:
    """Resolve a list of role strings to one active agent id each (best effort)."""
    ids: list = []
    for raw in roles or []:
        name = str(raw or "").strip()
        if not name or name.lower() == _FOUNDER:
            continue
        try:
            role = AgentRole(name.lower())
        except ValueError:
            continue
        agent = await _active_agent_for_role(db, company_id=company_id, role=role)
        if agent is not None:
            ids.append(agent.id)
    return ids


async def _resolve_recipient(db, *, company_id, to: str):
    """Map a ``to`` string to ``(agent_id_or_None, label, error)``.

    ``None`` agent id means the founder. Tries an exact name match first, then a
    role, so 'research' and a named agent both work.
    """
    target = str(to or "").strip()
    if not target:
        return None, None, "Specify who to message (an agent role/name, or 'founder')."
    if target.lower() == _FOUNDER:
        return None, "the founder", None

    by_name = await db.scalar(
        select(Agent).where(
            Agent.company_id == company_id, func.lower(Agent.name) == target.lower()
        )
    )
    if by_name is not None:
        return by_name.id, f"{by_name.name} ({by_name.role.value})", None

    try:
        role = AgentRole(target.lower())
    except ValueError:
        return None, None, f"No agent or role matching {target!r}."
    agent = await _active_agent_for_role(db, company_id=company_id, role=role)
    if agent is None:
        return None, None, f"No active {target} agent to message."
    return agent.id, f"{agent.name} ({agent.role.value})", None


async def _render_messages(db, msgs) -> str:
    lines = []
    for m in msgs:
        label = await chat.sender_label(db, m)
        lines.append(chat.render_message(m, label))
    return "\n".join(lines)


async def _park(db, task: Task) -> None:
    """Flip the (possibly session-detached) task to the parked state and persist."""
    row = await db.get(Task, task.id)
    if row is not None:
        row.status = TaskStatus.waiting_approval
    task.status = TaskStatus.waiting_approval  # keep the in-memory copy consistent


async def _post_and_maybe_wait(
    db,
    ctx,
    *,
    agent: Agent,
    task: Task,
    channel,
    body: str,
    wait: bool,
    context_label: str | None = None,
) -> ToolOutcome:
    """Shared send path for channels, DMs, and founder escalations.

    ``context_label`` overrides how the place is named in observations (so a
    founder escalation reads naturally instead of as a ``#channel`` post).
    """
    where = context_label or f"#{channel.name}"
    if wait:
        existing = await chat.pending_wait_for_task(db, task_id=task.id, channel_id=channel.id)
        if existing is not None and existing.status is ChatWaitStatus.satisfied:
            # Resume after a reply arrived: deliver it, don't re-post the message.
            replies = await chat.replies_for_wait(db, wait=existing)
            existing.status = ChatWaitStatus.consumed
            await db.flush()
            rendered = await _render_messages(db, replies)
            obs = (
                f"Reply in {where}:\n{rendered}"
                if rendered
                else f"Your task resumed but no reply has arrived in {where} yet."
            )
            return ToolOutcome(observation=clip(obs, _MAX_CHARS))
        if existing is not None and existing.status is ChatWaitStatus.pending:
            # Already parked on this channel; keep waiting (don't double-post).
            await _park(db, task)
            await db.flush()
            return ToolOutcome(observation=f"Still waiting for a reply in {where}.", park=True)

    # First call: actually post the message (and wake anyone waiting on this channel).
    _, woken = await chat.post_message(
        db,
        company_id=task.company_id,
        channel_id=channel.id,
        sender_agent_id=agent.id,
        body=body,
    )
    for task_id in woken:
        await ctx.enqueue_task(task_id)

    if not wait:
        return ToolOutcome(observation=f"Posted to {where}.")

    db.add(
        ChatWait(
            company_id=task.company_id,
            channel_id=channel.id,
            task_id=task.id,
            agent_id=agent.id,
            status=ChatWaitStatus.pending,
        )
    )
    await _park(db, task)
    await db.flush()
    return ToolOutcome(observation=f"Posted to {where} and waiting for a reply.", park=True)


async def escalate_to_founder(db, ctx, *, agent: Agent, task: Task, summary: str) -> ToolOutcome:
    """Open-ended escalation to the founder, as a DM that waits for their reply.

    The unified replacement for the old ``request_decision`` parking: the question
    becomes a message in the agent↔founder DM thread and the task parks on a
    :class:`ChatWait` until the founder replies, which resumes the agent with the
    reply delivered straight into its context. Idempotent on resume (it won't
    re-post the question), like every other waiting send.
    """
    channel = await chat.founder_dm(db, company_id=task.company_id, agent_id=agent.id)
    return await _post_and_maybe_wait(
        db,
        ctx,
        agent=agent,
        task=task,
        channel=channel,
        body=summary,
        wait=True,
        context_label="your DM with the founder",
    )


# ── Handlers ──────────────────────────────────────────────────────────────────
async def _list_chat_channels(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    channels = (
        await db.scalars(
            select(chat.ChatChannel)
            .where(
                chat.ChatChannel.company_id == task.company_id,
                chat.ChatChannel.archived.is_(False),
            )
            .order_by(chat.ChatChannel.created_at.desc())
            .limit(50)
        )
    ).all()
    if not channels:
        return ToolOutcome(
            observation="No chat channels yet. Start one with start_chat_channel, or DM a teammate."
        )
    lines = []
    for ch in channels:
        members = []
        for p in await chat.participants(db, ch.id):
            if p.agent_id is None:
                members.append("founder")
            else:
                a = await db.get(Agent, p.agent_id)
                members.append(a.role.value if a else "?")
        recent = await chat.messages(db, channel_id=ch.id, limit=1)
        last = ""
        if recent:
            label = await chat.sender_label(db, recent[-1])
            last = f" — last: {label}: {recent[-1].body[:60]}"
        kind = "DM" if ch.kind.value == "direct" else "channel"
        purpose = f" ({ch.purpose[:80]})" if ch.purpose else ""
        lines.append(f"- #{ch.name} [{kind}] members: {', '.join(members)}{purpose}{last}")
    return ToolOutcome(observation=clip("Chat channels:\n" + "\n".join(lines), _MAX_CHARS))


async def _start_chat_channel(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    name = str(args.get("name") or "").strip()
    if not name:
        return ToolOutcome(observation="A channel needs a name.", is_error=True)
    purpose = str(args.get("purpose") or "").strip() or None
    member_ids = await _resolve_member_ids(
        db, company_id=task.company_id, roles=args.get("members") or []
    )
    channel = await chat.create_channel(
        db,
        company_id=task.company_id,
        name=name,
        purpose=purpose,
        created_by_agent_id=agent.id,
        member_agent_ids=member_ids,
    )
    await db.flush()
    members = []
    for p in await chat.participants(db, channel.id):
        if p.agent_id is None:
            members.append("founder")
        else:
            a = await db.get(Agent, p.agent_id)
            members.append(a.role.value if a else "?")
    return ToolOutcome(
        observation=(
            f"Opened #{channel.name} with members: {', '.join(members)}. "
            "Post to it with send_chat_message."
        )
    )


async def _read_chat_channel(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    name = str(args.get("channel") or "").strip()
    channel = await chat.find_channel_by_name(db, company_id=task.company_id, name=name)
    if channel is None:
        return ToolOutcome(
            observation=f"No channel named {name!r}. Use list_chat_channels to see what exists.",
            is_error=True,
        )
    msgs = await chat.messages(db, channel_id=channel.id, limit=50)
    if not msgs:
        return ToolOutcome(observation=f"#{channel.name} has no messages yet.")
    rendered = await _render_messages(db, msgs)
    return ToolOutcome(observation=clip(f"#{channel.name}:\n{rendered}", _MAX_CHARS))


async def _send_chat_message(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    name = str(args.get("channel") or "").strip()
    body = str(args.get("message") or "").strip()
    if not body:
        return ToolOutcome(observation="Can't send an empty message.", is_error=True)
    channel = await chat.find_channel_by_name(db, company_id=task.company_id, name=name)
    if channel is None:
        return ToolOutcome(
            observation=(
                f"No channel named {name!r}. Start it with start_chat_channel, or "
                "use list_chat_channels to find the right one."
            ),
            is_error=True,
        )
    return await _post_and_maybe_wait(
        db,
        ctx,
        agent=agent,
        task=task,
        channel=channel,
        body=body,
        wait=bool(args.get("wait_for_reply")),
    )


async def _message_teammate(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    body = str(args.get("message") or "").strip()
    if not body:
        return ToolOutcome(observation="Can't send an empty message.", is_error=True)
    recipient_id, label, error = await _resolve_recipient(
        db, company_id=task.company_id, to=str(args.get("to") or "")
    )
    if error is not None:
        return ToolOutcome(observation=error, is_error=True)
    if recipient_id == agent.id:
        return ToolOutcome(observation="You can't DM yourself.", is_error=True)

    other_label = "founder" if recipient_id is None else (label or "agent")
    channel = await chat.get_or_create_direct(
        db,
        company_id=task.company_id,
        agent_a_id=agent.id,
        agent_b_id=recipient_id,
        name=f"DM: {agent.role.value} ↔ {other_label}",
    )
    await db.flush()
    return await _post_and_maybe_wait(
        db,
        ctx,
        agent=agent,
        task=task,
        channel=channel,
        body=body,
        wait=bool(args.get("wait_for_reply")),
    )


HANDLERS = {
    "list_chat_channels": _list_chat_channels,
    "start_chat_channel": _start_chat_channel,
    "read_chat_channel": _read_chat_channel,
    "send_chat_message": _send_chat_message,
    "message_teammate": _message_teammate,
}
