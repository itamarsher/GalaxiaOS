"""Governance policy engine.

Declarative JSONB rules evaluated before every tool execution. The vocabulary is
deliberately small (tool match, numeric compare on a field, agent-role match) —
no Turing-complete DSL. Policies are ordered by priority; the first matching
``deny``/``require_approval`` wins, with ``deny`` winning ties.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Policy
from app.models.enums import PolicyEffect, PolicyScope

_OPS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


def _matches(rule: dict, action: dict[str, Any]) -> bool:
    """AND of whatever conditions the rule specifies."""
    if "tool" in rule and action.get("tool") != rule["tool"]:
        return False
    if "role_in" in rule and action.get("agent_role") not in rule["role_in"]:
        return False
    # ``is_external`` gates an entire class of actions — every tool that sends a
    # message outside the company — without enumerating tool names, so one rule
    # can require approval for all outbound communication (see EXTERNAL_COMMS_*).
    if "is_external" in rule and bool(action.get("is_external")) != bool(rule["is_external"]):
        return False
    if "field" in rule:
        field, op, value = rule.get("field"), rule.get("op", "=="), rule.get("value")
        actual = action.get(field)
        if actual is None or op not in _OPS:
            return False
        try:
            if not _OPS[op](actual, value):
                return False
        except TypeError:
            return False
    return True


async def evaluate(
    db: AsyncSession, *, company_id: uuid.UUID, action: dict[str, Any]
) -> PolicyEffect:
    """Return the governing effect for an action (default ``allow``)."""
    policies = (
        await db.scalars(
            select(Policy)
            .where(Policy.company_id == company_id, Policy.enabled.is_(True))
            .order_by(Policy.priority.asc())
        )
    ).all()

    decision: PolicyEffect | None = None
    for p in policies:
        if _matches(p.rule, action):
            if p.effect is PolicyEffect.deny:
                return PolicyEffect.deny  # deny wins immediately
            if p.effect is PolicyEffect.require_approval and decision is None:
                decision = PolicyEffect.require_approval
    return decision or PolicyEffect.allow


async def get_external_comms_approval(
    db: AsyncSession, *, company_id: uuid.UUID
) -> bool:
    """Whether the "every external communication needs approval" policy is on."""
    policy = await _external_comms_policy(db, company_id=company_id)
    return bool(policy and policy.enabled)


async def set_external_comms_approval(
    db: AsyncSession, *, company_id: uuid.UUID, enabled: bool
) -> bool:
    """Enable/disable the external-communication approval guardrail, creating the
    named policy on first use. Returns the resulting enabled state."""
    policy = await _external_comms_policy(db, company_id=company_id)
    spec = external_comms_approval_spec(enabled=enabled)
    if policy is None:
        policy = Policy(
            company_id=company_id,
            name=spec["name"],
            scope=PolicyScope(spec["scope"]),
            rule=spec["rule"],
            effect=PolicyEffect(spec["effect"]),
            priority=spec["priority"],
            enabled=enabled,
        )
        db.add(policy)
    else:
        policy.enabled = enabled
        # Self-heal an older/edited row back to the canonical rule + effect.
        policy.rule = spec["rule"]
        policy.effect = PolicyEffect(spec["effect"])
    await db.flush()
    return enabled


async def _external_comms_policy(
    db: AsyncSession, *, company_id: uuid.UUID
) -> Policy | None:
    return await db.scalar(
        select(Policy).where(
            Policy.company_id == company_id,
            Policy.name == EXTERNAL_COMMS_APPROVAL_POLICY,
        )
    )


# The founder-approval guardrail for outbound communication. A single named,
# toggleable policy so the UI can flip it on/off (see app.api.comms) rather than
# making the founder hand-author a JSON rule. Highest priority so it gates before
# any narrower allow.
EXTERNAL_COMMS_APPROVAL_POLICY = "Every external communication needs founder approval"


def external_comms_approval_spec(*, enabled: bool) -> dict:
    """The canonical spec for the external-communication approval policy."""
    return {
        "name": EXTERNAL_COMMS_APPROVAL_POLICY,
        "scope": "global",
        "rule": {"is_external": True},
        "effect": "require_approval",
        "priority": 5,
        "enabled": enabled,
    }


def default_policies() -> list[dict]:
    """Seed policies created at launch."""
    return [
        {
            "name": "Never spend more than $100 without approval",
            "scope": "category",
            "rule": {"field": "amount_cents", "op": ">", "value": 10000},
            "effect": "require_approval",
            "priority": 10,
        },
        {
            "name": "Domain purchases require approval",
            "scope": "global",
            "rule": {"tool": "register_domain", "field": "amount_cents", "op": ">", "value": 5000},
            "effect": "require_approval",
            "priority": 20,
        },
    ]
