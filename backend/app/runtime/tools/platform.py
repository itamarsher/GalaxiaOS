"""Platform agent tools: escalation triggers + issue filing.

The Platform agent is dormant: the CEO's normal planning never dispatches it.
Instead, ANY agent that hits a limitation wakes it through two trigger tools —
``report_bug`` (something is broken) and ``request_capability`` (I lack a tool).
Each spawns a queued task to the Platform agent (reusing the same ``_spawn_child``
delegation mechanism the CEO uses) and returns immediately, so the reporting
agent never stalls on its own task.

Once awake, the Platform agent investigates this codebase with the read-only
``list_repo_files`` / ``read_repo_file`` tools (in ``code.py``) and files a
precise tracker issue with ``open_issue``, which routes through the
:mod:`app.integrations.issues` seam and records the issue to company memory for an
audit trail. Filing an issue is a platform/meta action — it carries no budget
charge.
"""

from __future__ import annotations

from sqlalchemy import select

from app.config import settings
from app.integrations.issues import (
    GitHubIssueTracker,
    IssueTrackerError,
    get_issue_tracker,
)
from app.models import Agent, Task
from app.models.enums import AgentRole, MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.runtime.tools.core import _spawn_child
from app.services import apikeys

#: Provider name under which a company's GitHub token is stored (BYOK).
GITHUB_PROVIDER = "github"


async def _resolve_issue_tracker(db, company_id):
    """Use the company's own GitHub token if it set one, else the global default.

    A founder can attach a GitHub token per company (in onboarding or Settings);
    when present we file real issues against ``settings.github_repo``. Without one
    we fall back to the configured default tracker (offline simulated unless the
    deployment set a global GitHub token).
    """
    token = await apikeys.get_plaintext_key(
        db, company_id=company_id, provider=GITHUB_PROVIDER
    )
    if token:
        return GitHubIssueTracker(token, repo=settings.github_repo)
    return get_issue_tracker()

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="report_bug",
        description=(
            "Report a bug or broken behaviour to the Platform agent. Use this when "
            "you hit something that is clearly malfunctioning (a tool errors, a "
            "result is wrong) rather than stalling your own task. The Platform agent "
            "will investigate the codebase and file a tracker issue; you can carry on "
            "with your task."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short summary of the bug."},
                "details": {
                    "type": "string",
                    "description": (
                        "What you were doing, what happened, and what you expected — "
                        "enough for the Platform agent to investigate."
                    ),
                },
            },
            "required": ["title", "details"],
        },
    ),
    ToolSpec(
        name="request_capability",
        description=(
            "Request a new capability or tool from the Platform agent. Use this when "
            "you lack a tool you need to do your job, instead of giving up on the task. "
            "The Platform agent will assess feasibility against the codebase and file a "
            "feature-request issue; you can carry on with your task."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short summary of the capability."},
                "details": {
                    "type": "string",
                    "description": (
                        "What capability you need and why — the gap it would close in "
                        "your work."
                    ),
                },
            },
            "required": ["title", "details"],
        },
    ),
    ToolSpec(
        name="open_issue",
        description=(
            "Platform agent: file a tracker issue (bug or feature request). Routes "
            "through the configured issue tracker (offline simulated by default; "
            "GitHub when credentials are set) and records the filed issue to company "
            "memory for the audit trail. Investigate the relevant code with "
            "`list_repo_files` / `read_repo_file` first so the issue is precise."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {
                    "type": "string",
                    "description": "The issue body, in Markdown.",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional labels, e.g. ['bug'] or ['enhancement'].",
                },
            },
            "required": ["title", "body"],
        },
    ),
]


async def _has_platform_agent(db, company_id) -> bool:
    return (
        await db.scalar(
            select(Agent.id).where(
                Agent.company_id == company_id, Agent.role == AgentRole.platform
            )
        )
    ) is not None


async def _trigger_platform(
    db, ctx, *, agent: Agent, task: Task, kind: str, title: str, details: str
) -> ToolOutcome:
    """Spawn a queued task to the Platform agent describing the report."""
    if not await _has_platform_agent(db, task.company_id):
        return ToolOutcome(
            observation=(
                "No Platform agent exists for this company, so the report could not be "
                "filed. Carry on with your task."
            ),
            is_error=True,
        )
    if kind == "bug":
        goal = (
            f"A {agent.role.value} agent reported a BUG: {title}\n\n"
            f"Details:\n{details}\n\n"
            "Investigate the relevant code with `list_repo_files` / `read_repo_file`, "
            "then file a precise bug issue with `open_issue` (label it 'bug') and "
            "report what you filed."
        )
    else:
        goal = (
            f"A {agent.role.value} agent REQUESTED A CAPABILITY: {title}\n\n"
            f"Details:\n{details}\n\n"
            "Assess feasibility against the codebase with `list_repo_files` / "
            "`read_repo_file`, then file a feature-request issue with `open_issue` "
            "(label it 'enhancement') and report what you filed."
        )
    await _spawn_child(db, ctx, task, agent, AgentRole.platform.value, goal)
    label = "bug report" if kind == "bug" else "capability request"
    return ToolOutcome(
        observation=(
            f"Filed a {label} with the Platform agent: {title[:80]!r}. It will "
            "investigate and open a tracker issue; carry on with your task."
        )
    )


async def _report_bug(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return await _trigger_platform(
        db,
        ctx,
        agent=agent,
        task=task,
        kind="bug",
        title=str(args["title"]).strip(),
        details=str(args["details"]).strip(),
    )


async def _request_capability(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return await _trigger_platform(
        db,
        ctx,
        agent=agent,
        task=task,
        kind="capability",
        title=str(args["title"]).strip(),
        details=str(args["details"]).strip(),
    )


async def _open_issue(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.services import memory as memory_svc

    title = str(args["title"]).strip()
    body = str(args["body"]).strip()
    labels = [str(x) for x in (args.get("labels") or []) if str(x).strip()]
    try:
        tracker = await _resolve_issue_tracker(db, task.company_id)
        result = await tracker.open_issue(title=title, body=body, labels=labels)
    except IssueTrackerError as exc:
        return ToolOutcome(observation=f"could not open issue: {exc}", is_error=True)

    # Audit trail: record the filed issue to company memory.
    label_part = f" [{', '.join(labels)}]" if labels else ""
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Issue filed: {title[:80]}",
        content=(
            f"Tracker issue #{result.number} opened via {result.provider}{label_part}.\n"
            f"URL: {result.url}\n\n{body[:2000]}"
        ),
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=(
            f"opened issue #{result.number} via {result.provider} "
            f"(id {result.id}, {result.url})"
        )
    )


HANDLERS = {
    "report_bug": _report_bug,
    "request_capability": _request_capability,
    "open_issue": _open_issue,
}
