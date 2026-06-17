"""Founder-initiated platform requests (bug reports / capability requests).

Agents file these via the ``report_bug`` / ``request_capability`` tools, but the
founder also needs to file one directly when chatting with the copilot or an
agent ("request web search"). This creates the same unit of work — a queued task
for the (idle) Platform agent, which investigates the codebase and opens a
tracker issue — from an API/chat context where there's no parent task or runtime
``ctx`` to spawn a child from.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.runtime.breakers import loop_signature

#: Accepted request kinds -> (issue label, how the goal frames it).
_KINDS = {
    "bug": ("bug", "reported a BUG"),
    "capability": ("enhancement", "REQUESTED A CAPABILITY"),
}


async def file_request(
    db: AsyncSession, *, company_id: uuid.UUID, kind: str, title: str, details: str
) -> uuid.UUID | None:
    """Create a queued task for the Platform agent. Returns the task id to enqueue.

    Returns ``None`` if the kind is unknown or the company has no Platform agent.
    The caller commits and then enqueues the returned id.
    """
    if kind not in _KINDS:
        return None
    platform = await db.scalar(
        select(Agent).where(
            Agent.company_id == company_id, Agent.role == AgentRole.platform
        )
    )
    if platform is None:
        return None

    label, framing = _KINDS[kind]
    goal = (
        f"The founder {framing}: {title}\n\n"
        f"Details:\n{details}\n\n"
        "Investigate the relevant code with `list_repo_files` / `read_repo_file`, "
        f"then file a precise issue with `open_issue` (label it '{label}') and report "
        "what you filed."
    )

    run = AgentRun(
        company_id=company_id, trigger=RunTrigger.founder_command, status=RunStatus.running
    )
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    task = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=platform.id,
        depth=0,
        goal=goal,
        status=TaskStatus.queued,
        loop_signature=loop_signature(platform.id, title),
    )
    db.add(task)
    await db.flush()
    return task.id
