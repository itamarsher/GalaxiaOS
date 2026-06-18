"""Marketing area tools: publish content, schedule social posts, run ad campaigns.

These reach the world OUTSIDE the company (a CMS/social API, an ad network) and
there is no real provider wired for them, so they are unsupported here. They used
to fabricate a published URL / scheduled post / launched campaign (and
``run_ad_campaign`` even charged the budget for an action that never happened). Each
handler now reports the capability is unavailable and points the agent at
``request_capability`` rather than returning a fake success that pollutes memory,
metrics, and plans.
"""

from __future__ import annotations

from app.models import Agent, Task
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome, unsupported_capability

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="publish_content",
        description=(
            "Publish a piece of marketing content (blog post, landing page, social "
            "post, or email) and return its published URL."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "channel": {
                    "type": "string",
                    "enum": ["blog", "landing_page", "social", "email"],
                },
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["channel", "title", "body"],
        },
    ),
    ToolSpec(
        name="schedule_social_post",
        description="Schedule a social media post for later publishing on a platform.",
        input_schema={
            "type": "object",
            "properties": {
                "platform": {"type": "string"},
                "content": {"type": "string"},
                "when": {
                    "type": "string",
                    "description": "Optional ISO timestamp / human time to publish at.",
                },
            },
            "required": ["platform", "content"],
        },
    ),
    ToolSpec(
        name="run_ad_campaign",
        description=(
            "Launch a paid ad campaign on a platform. SPENDS real budget: the "
            "amount_cents is charged through the cost meter and gated by governance."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "platform": {"type": "string"},
                "objective": {"type": "string"},
                "amount_cents": {
                    "type": "integer",
                    "description": "Budget to spend on the campaign, in cents.",
                },
            },
            "required": ["platform", "objective", "amount_cents"],
        },
    ),
]


async def _publish_content(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return unsupported_capability(
        "Publishing marketing content",
        hint="No CMS/website provider is connected to publish to.",
    )


async def _schedule_social_post(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return unsupported_capability(
        "Scheduling a social post",
        hint="No social-media provider is connected.",
    )


async def _run_ad_campaign(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    # Note: no budget is charged — the campaign would not actually run.
    return unsupported_capability(
        "Running an ad campaign",
        hint="No ad network is connected, so the budget was NOT charged.",
    )


HANDLERS = {
    "publish_content": _publish_content,
    "schedule_social_post": _schedule_social_post,
    "run_ad_campaign": _run_ad_campaign,
}
