"""Report tool: file a founder-facing deliverable (artifact).

``create_report`` lets an agent hand the founder a synthesized deliverable — an
investor update, a growth or research report, a board brief — that lands in the
Reports tab. It is internal-facing: filing a report does NOT send anything outside
the company (that is what the egress tools, e.g. send_email, are for).
"""

from __future__ import annotations

from app.models import Agent, Task
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import artifacts as artifacts_svc

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="create_report",
        description=(
            "File a founder-facing report/deliverable (e.g. investor update, growth or "
            "research report, board brief). It is saved to the founder's Reports for them "
            "to read — it does NOT send anything externally. Use when you've synthesized "
            "something the founder should see."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "Report kind, e.g. investor_update, growth_report, research_report, board_brief, custom.",
                },
                "title": {"type": "string"},
                "body_md": {"type": "string", "description": "The full report in Markdown."},
            },
            "required": ["title", "body_md"],
        },
    ),
]


async def _create_report(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    title = str(args.get("title") or "").strip()
    body = str(args.get("body_md") or "").strip()
    if not title or not body:
        return ToolOutcome(
            observation="create_report needs both a title and body_md.", is_error=True
        )
    artifact = await artifacts_svc.create_artifact(
        db,
        company_id=task.company_id,
        kind=str(args.get("kind") or "custom"),
        title=title,
        body_md=body,
        source_task_id=task.id,
        source_agent_id=agent.id,
    )
    return ToolOutcome(
        observation=f"filed report “{artifact.title}” ({artifact.kind}) to the founder's Reports"
    )


HANDLERS = {"create_report": _create_report}
