"""Marketing area tools: publish content, schedule social posts, run ad campaigns.

These are the marketing-specific tools an agent uses to grow the business. They
are SIMULATED and deterministic by default — ``publish_content`` and
``schedule_social_post`` perform no network I/O, while ``run_ad_campaign`` is the
only one that spends real budget and therefore routes its charge through
``ctx.cost_meter`` (the same chokepoint as LLM calls), keeping ``amount_cents``
as a top-level arg so governance and the spend breaker can gate it up front.
"""

from __future__ import annotations

import hashlib

from app.integrations.marketing import get_publisher, published_url
from app.models import Agent, Task
from app.models.enums import MemoryType, MetricSource
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import memory as memory_svc
from app.services import metrics as metrics_svc

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
    channel = args["channel"]
    title = args["title"]
    body = args["body"]

    result = await get_publisher().publish(channel=channel, title=title, body=body)

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Published: {title}",
        content=f"{channel} -> {result.url}\n\n{body[:2000]}",
        source_task_id=task.id,
    )
    await metrics_svc.record_signal(
        db,
        company_id=task.company_id,
        name="content_published",
        value=1,
        source=MetricSource.agent,
        note=f"{channel}: {title[:80]}",
    )
    return ToolOutcome(observation=f"published {channel} content {title[:60]!r} at {result.url}")


async def _schedule_social_post(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    platform = args["platform"]
    content = args["content"]
    when = args.get("when")

    digest = hashlib.sha256(f"{platform}|{content}|{when or ''}".encode()).hexdigest()[:12]
    post_id = f"sched:{platform}:{digest}"
    when_label = when or "next available slot"

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.decision,
        title=f"Scheduled social post on {platform}",
        content=f"id={post_id} when={when_label}\n\n{content[:2000]}",
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=f"scheduled post {post_id} on {platform} for {when_label}"
    )


async def _run_ad_campaign(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    platform = args["platform"]
    objective = args["objective"]
    amount_cents = int(args["amount_cents"])

    try:
        await ctx.cost_meter.charge_external(
            company_id=task.company_id,
            agent_id=agent.id,
            task_id=task.id,
            amount_cents=amount_cents,
            vendor=f"ads:{platform}",
            sku=objective,
            description=f"ad campaign on {platform} ({objective})",
        )
    except Exception as exc:  # refused / over-budget must never crash the loop
        return ToolOutcome(observation=f"ad campaign not funded: {exc}", is_error=True)

    note = f"{platform} campaign, objective={objective}"
    await metrics_svc.record_signal(
        db,
        company_id=task.company_id,
        name="ad_spend",
        value=amount_cents / 100,
        unit="USD",
        source=MetricSource.agent,
        note=note,
    )
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.decision,
        title=f"Ran ad campaign on {platform}",
        content=f"objective={objective} budget=${amount_cents / 100:.2f}",
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=(
            f"launched {platform} ad campaign (objective {objective!r}, "
            f"spend ${amount_cents / 100:.2f})"
        )
    )


# Re-export so callers/tests can reach the deterministic URL helper from here too.
__all__ = ["SPECS", "HANDLERS", "published_url"]


HANDLERS = {
    "publish_content": _publish_content,
    "schedule_social_post": _schedule_social_post,
    "run_ad_campaign": _run_ad_campaign,
}
