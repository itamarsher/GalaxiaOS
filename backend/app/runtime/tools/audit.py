"""CEO audit tool: accept or challenge a delegated result sitting in ``auditing``.

A delegated agent's result doesn't go straight to ``done`` — it lands in
``auditing`` and the CEO is woken with a task to review it (see
:mod:`app.services.tasks`). From that audit task the CEO calls ``audit_task`` to
transition the result forward (``approve`` → ``done``) or backward (``reopen`` →
re-queued). On a reopen the CEO's comments are stored on the task and the agent
loop surfaces them as its first instruction when it resumes with full context.
"""

from __future__ import annotations

import uuid

from app.models import Agent, Task
from app.models.enums import AgentRole, TaskStatus
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import tasks as task_svc

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="audit_task",
        description=(
            "CEO only. Audit a delegated result that is waiting in 'auditing'. "
            "Transition it forward by approving it (accept the work → done), or "
            "backward by reopening it (send it back for rework). When you reopen, "
            "your comments are handed to the agent as its first instruction when it "
            "resumes with its full prior context, so be specific about what to fix. "
            "Use this to challenge weak or incomplete results rather than letting "
            "them stand."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The id of the task under audit (given in your audit goal).",
                },
                "decision": {
                    "type": "string",
                    "enum": ["approve", "reopen"],
                    "description": "approve = accept (forward to done); reopen = send back for rework.",
                },
                "comments": {
                    "type": "string",
                    "description": (
                        "Your audit comments. Required when reopening — the specific "
                        "changes the agent must make."
                    ),
                },
            },
            "required": ["task_id", "decision"],
        },
    ),
]


async def _audit_task(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if agent.role is not AgentRole.ceo:
        return ToolOutcome(
            observation="Only the CEO can audit delegated results.", is_error=True
        )

    try:
        target_id = uuid.UUID(str(args.get("task_id") or "").strip())
    except (ValueError, AttributeError):
        return ToolOutcome(observation="Provide a valid task_id to audit.", is_error=True)

    decision = str(args.get("decision") or "").strip().lower()
    if decision not in ("approve", "reopen"):
        return ToolOutcome(
            observation="decision must be 'approve' or 'reopen'.", is_error=True
        )

    target = await db.get(Task, target_id)
    if target is None or target.company_id != task.company_id:
        return ToolOutcome(observation="No such task to audit.", is_error=True)
    if target.status is not TaskStatus.auditing:
        return ToolOutcome(
            observation=(
                f"That task isn't awaiting audit (it's {target.status.value}); nothing to do."
            ),
            is_error=True,
        )

    comments = str(args.get("comments") or "").strip()

    if decision == "approve":
        output = dict(target.output or {})
        if comments:
            output["audit_comments"] = comments
        await task_svc.finalize(db, task=target, status=TaskStatus.done, output=output)
        await db.flush()
        return ToolOutcome(observation=f"Approved task {target_id}: accepted as done.")

    # reopen → re-queue with the CEO's comments as the agent's next instruction.
    if not comments:
        return ToolOutcome(
            observation="Reopening needs comments telling the agent what to fix.",
            is_error=True,
        )
    rounds = int((target.input or {}).get("audit_rounds", 0)) + 1
    target.input = {
        **(target.input or {}),
        "audit_feedback": comments,
        "audit_rounds": rounds,
    }
    target.status = TaskStatus.queued
    await db.flush()
    await ctx.enqueue_task(target.id)
    return ToolOutcome(
        observation=(
            f"Reopened task {target_id} (audit round {rounds}); the agent will resume "
            "with your comments and its prior context."
        )
    )


HANDLERS = {"audit_task": _audit_task}
