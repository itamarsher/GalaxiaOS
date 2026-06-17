"""Data agent tools: control what data is shared OUTSIDE the company.

The egress tools below are how data leaves the company (email, published content,
social posts, ad campaigns, notifications). Because ``governance.evaluate`` runs
on every tool call, the Data agent can govern egress simply by managing Policy
rows that name an egress tool — ``set_external_sharing_policy`` upserts one and it
takes effect immediately, ``list_data_policies`` reports the current posture.

Pairs with ``code.py`` (the codebase-reading tools) to give the Data agent its
two halves: internal data access and external-sharing control.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, Policy, Task
from app.models.enums import PolicyEffect, PolicyScope
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome

# Tools that send data to entities OUTSIDE the company. These are the ONLY tools
# the Data agent may govern with an external-sharing policy — keep in sync with
# the outbound tools in core/marketing/ops.
_EGRESS_TOOLS = (
    "send_email",
    "publish_content",
    "schedule_social_post",
    "run_ad_campaign",
    "send_notification",
)

_EFFECTS = ("allow", "deny", "require_approval")


def _policy_name(tool: str) -> str:
    return f"Data egress: {tool}"


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="set_external_sharing_policy",
        description=(
            "Control whether an outbound tool may share data outside the company. "
            "Upserts a governance policy for one egress tool with the given effect "
            "(allow / deny / require_approval); enforced immediately on every call "
            f"of that tool. Egress tools: {', '.join(_EGRESS_TOOLS)}."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "tool": {"type": "string", "enum": list(_EGRESS_TOOLS)},
                "effect": {"type": "string", "enum": list(_EFFECTS)},
                "reason": {
                    "type": "string",
                    "description": "Optional note explaining the decision.",
                },
            },
            "required": ["tool", "effect"],
        },
    ),
    ToolSpec(
        name="list_data_policies",
        description=(
            "List the current external-sharing policies (one per egress tool that has "
            "been governed) with their effects, as a readable summary."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
]


async def _set_external_sharing_policy(
    db, ctx, *, agent: Agent, task: Task, args: dict
) -> ToolOutcome:
    tool = str(args.get("tool") or "").strip()
    effect = str(args.get("effect") or "").strip()
    reason = str(args.get("reason") or "").strip()
    if tool not in _EGRESS_TOOLS:
        return ToolOutcome(
            observation=(
                f"{tool!r} is not a known egress tool; choose one of {', '.join(_EGRESS_TOOLS)}."
            ),
            is_error=True,
        )
    if effect not in _EFFECTS:
        return ToolOutcome(
            observation=f"{effect!r} is not a valid effect; choose one of {', '.join(_EFFECTS)}.",
            is_error=True,
        )

    name = _policy_name(tool)
    # Upsert by name so re-setting a tool's effect replaces the prior decision
    # instead of stacking duplicate rows.
    policy = await db.scalar(
        select(Policy).where(Policy.company_id == task.company_id, Policy.name == name)
    )
    if policy is None:
        policy = Policy(
            company_id=task.company_id,
            name=name,
            scope=PolicyScope.category,
            rule={"tool": tool},
            effect=PolicyEffect(effect),
        )
        db.add(policy)
    else:
        policy.rule = {"tool": tool}
        policy.effect = PolicyEffect(effect)
        policy.enabled = True
    await db.flush()

    note = f" ({reason})" if reason else ""
    return ToolOutcome(
        observation=f"external-sharing policy set: {tool} -> {effect}{note}"
    )


async def _list_data_policies(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    policies = (
        await db.scalars(
            select(Policy)
            .where(Policy.company_id == task.company_id)
            .order_by(Policy.name.asc())
        )
    ).all()
    rows = [
        (p.rule["tool"], p.effect.value, "" if p.enabled else " (disabled)")
        for p in policies
        if isinstance(p.rule, dict) and p.rule.get("tool") in _EGRESS_TOOLS
    ]
    if not rows:
        return ToolOutcome(
            observation=(
                "No external-sharing policies set; all egress tools default to allow. "
                "Use set_external_sharing_policy to restrict one."
            )
        )
    lines = [f"- {tool}: {effect}{suffix}" for tool, effect, suffix in rows]
    return ToolOutcome(observation="External-sharing policies:\n" + "\n".join(lines))


HANDLERS = {
    "set_external_sharing_policy": _set_external_sharing_policy,
    "list_data_policies": _list_data_policies,
}
