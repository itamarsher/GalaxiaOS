"""CEO review tools: audit a delegated result, or retry a failed delegated task.

A delegated agent's work doesn't reach a terminal state on its own — it lands in
``auditing`` and the CEO is woken with a task to review it (see
:mod:`app.services.tasks`):

- A successful result → ``audit_task``: transition it forward (``approve`` → done)
  or backward (``reopen`` → re-queued with the CEO's comments as the agent's next
  instruction).
- A failed task → ``retry_task``: re-run it (``retry`` → re-queued) when the failure
  looks transient, or let it stand (``abandon`` → failed) when it's persistent. The
  per-task retry cap (``settings.max_task_retries``) stops a fail↔retry loop.
"""

from __future__ import annotations

import uuid

from app.config import settings
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
    ToolSpec(
        name="retry_task",
        description=(
            "CEO only. Decide what to do with a delegated task that FAILED and is "
            "waiting for your call. If the failure looks transient and not a "
            "persistent problem, re-run it (decision 'retry'); the task starts fresh "
            "from its goal. If it would just fail again (a missing capability, a "
            "malformed goal), abandon it (decision 'abandon') so it stays failed "
            "instead of burning budget. There is a per-task retry cap, so a task "
            "can't be re-run forever."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The id of the failed task (given in your review goal).",
                },
                "decision": {
                    "type": "string",
                    "enum": ["retry", "abandon"],
                    "description": "retry = re-run the task; abandon = let it stay failed.",
                },
                "reason": {
                    "type": "string",
                    "description": "Brief note on why you're retrying or abandoning.",
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


async def _retry_task(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if agent.role is not AgentRole.ceo:
        return ToolOutcome(
            observation="Only the CEO can decide on retrying a failed task.", is_error=True
        )

    try:
        target_id = uuid.UUID(str(args.get("task_id") or "").strip())
    except (ValueError, AttributeError):
        return ToolOutcome(observation="Provide a valid task_id to retry.", is_error=True)

    decision = str(args.get("decision") or "").strip().lower()
    if decision not in ("retry", "abandon"):
        return ToolOutcome(
            observation="decision must be 'retry' or 'abandon'.", is_error=True
        )

    target = await db.get(Task, target_id)
    if target is None or target.company_id != task.company_id:
        return ToolOutcome(observation="No such task to retry.", is_error=True)
    # Only a parked FAILURE review is retryable — not a result audit or a live task.
    if target.status is not TaskStatus.auditing or not (target.input or {}).get(
        "failure_review"
    ):
        return ToolOutcome(
            observation=(
                f"That task isn't awaiting a retry decision (it's {target.status.value}); "
                "nothing to do."
            ),
            is_error=True,
        )

    reason = str(args.get("reason") or "").strip()

    if decision == "abandon":
        output = dict(target.output or {})
        if reason:
            output["abandon_reason"] = reason
        # Clear the review marker so it settles cleanly as a terminal failure.
        target.input = {k: v for k, v in (target.input or {}).items() if k != "failure_review"}
        await task_svc.finalize(db, task=target, status=TaskStatus.failed, output=output)
        await db.flush()
        return ToolOutcome(
            observation=f"Abandoned failed task {target_id}: it stays failed (no retry)."
        )

    # retry → re-queue the task to run again from its goal, capped per task.
    retries = int((target.input or {}).get("retry_count", 0))
    if retries >= settings.max_task_retries:
        output = dict(target.output or {})
        output["abandon_reason"] = f"retry cap reached ({settings.max_task_retries})"
        target.input = {k: v for k, v in (target.input or {}).items() if k != "failure_review"}
        await task_svc.finalize(db, task=target, status=TaskStatus.failed, output=output)
        await db.flush()
        return ToolOutcome(
            observation=(
                f"Task {target_id} has already used all {settings.max_task_retries} "
                "retries; left as failed."
            ),
            is_error=True,
        )

    retries += 1
    target.input = {
        **{k: v for k, v in (target.input or {}).items() if k != "failure_review"},
        "retry_count": retries,
    }
    target.status = TaskStatus.queued
    await db.flush()
    await ctx.enqueue_task(target.id)
    return ToolOutcome(
        observation=(
            f"Re-running failed task {target_id} (retry {retries} of "
            f"{settings.max_task_retries}); it starts fresh from its goal."
        )
    )


HANDLERS = {"audit_task": _audit_task, "retry_task": _retry_task}
