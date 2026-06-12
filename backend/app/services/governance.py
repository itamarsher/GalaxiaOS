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
from app.models.enums import PolicyEffect

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
