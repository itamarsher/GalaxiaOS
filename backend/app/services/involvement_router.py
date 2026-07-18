"""Involvement router — decide when to route a decision/task to a human, and whom.

Replaces the old global autonomy scale (``DelegateAutonomy``) with per-person,
team-aware routing. Given a decision or task, it reads each member's
**founder-sanctioned** involvement prose (``Membership.involvement`` only — never a
pending proposal, so a teammate can't self-escalate) and, via the LLM, decides
whether a human should handle/approve it and which member.

Fail-safe by construction: if there is no model, or the model names no valid member
while still asking for human involvement, it defaults to the **founder** rather than
silently letting agents act — the founder is always the ultimate fallback for
anything a human must own.

This module is the routing decision; it is wired into the founder-decision triage
(``app.services.delegate`` / ``app.jobs.scheduled.triage_founder_decisions``),
which replaced the old ``DelegateAutonomy`` slider. The pure prompt-build and parse
helpers carry the logic and are unit-tested; the LLM call is thin.
"""

from __future__ import annotations

import json
import uuid

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models.enums import MembershipRole
from app.providers.base import Message
from app.runtime.cost_meter import CostMeter
from app.services import apikeys
from app.services import involvement as involvement_svc

_ROUTER_SYSTEM = (
    "You route work in an AI-run company to the right HUMAN when a human wants to be "
    "involved. You are given a decision or task and each team member's stated "
    "involvement preferences, in their own words. Decide whether a human should "
    "handle or approve this, and if so WHICH member.\n"
    "- Involve a human only when the subject genuinely matches how a member said they "
    "want to be involved.\n"
    "- Prefer the most specific match. The founder is the ultimate fallback for "
    "anything that requires human sign-off.\n"
    "- If no member's stated preferences call for human involvement, let the agents "
    "handle it autonomously.\n"
    'Reply with ONLY a JSON object: {"involve_human": true|false, "user_id": '
    '"<member id or null>", "reason": "<one short line>"}.'
)


class RoutingSubject(BaseModel):
    kind: str  # e.g. "spend_approval", "plan_approval", "task"
    summary: str
    detail: str = ""


class RoutingDecision(BaseModel):
    involve_human: bool
    user_id: uuid.UUID | None = None
    reason: str = ""


def build_team_block(members) -> str:
    """Render the team's SANCTIONED involvement for the prompt (skips the unstated)."""
    lines = []
    for m in members:
        if not m.involvement:
            continue  # only founder-sanctioned prose ever informs routing
        cov = f" (covers: {m.coverage})" if getattr(m, "coverage", None) else ""
        lines.append(f"- member {m.user_id} [{m.role.value}]{cov}: {m.involvement}")
    return "\n".join(lines) or "(no member has stated involvement preferences)"


def parse_decision(text: str, valid_user_ids: set[uuid.UUID]) -> RoutingDecision:
    """Parse the model's JSON verdict, validating the chosen member is real."""
    try:
        obj = json.loads(text[text.find("{") : text.rfind("}") + 1])
    except (ValueError, TypeError):
        return RoutingDecision(involve_human=False, reason="unparseable routing verdict")
    involve = bool(obj.get("involve_human"))
    user_id: uuid.UUID | None = None
    raw = obj.get("user_id")
    if raw:
        try:
            cand = uuid.UUID(str(raw))
            if cand in valid_user_ids:
                user_id = cand
        except (ValueError, TypeError):
            user_id = None
    return RoutingDecision(
        involve_human=involve, user_id=user_id, reason=str(obj.get("reason") or "")
    )


def _founder(members):
    return next((m for m in members if m.role is MembershipRole.founder), None)


async def route(
    db: AsyncSession, *, company_id: uuid.UUID, subject: RoutingSubject
) -> RoutingDecision:
    """Decide human involvement for ``subject`` against the team's stated preferences."""
    members = await involvement_svc.team_involvement(db, company_id=company_id)
    if not any(m.involvement for m in members):
        return RoutingDecision(involve_human=False, reason="no stated human involvement")

    resolved = await apikeys.resolve_active_provider(db, company_id=company_id)
    if resolved is None:
        # No model to reason with — fail safe to the founder rather than drop the
        # human's stated wish to be involved.
        f = _founder(members)
        return RoutingDecision(
            involve_human=f is not None,
            user_id=f.user_id if f else None,
            reason="no model available; defaulting to founder",
        )

    meter = CostMeter(SessionLocal)
    resp = await meter.run_llm(
        resolved.provider,
        api_key=resolved.api_key,
        company_id=company_id,
        agent_id=None,
        task_id=None,
        model=resolved.provider.default_models["cheap"],
        system=_ROUTER_SYSTEM,
        messages=[
            Message(
                role="user",
                content=(
                    f"Team involvement preferences:\n{build_team_block(members)}\n\n"
                    f"Subject ({subject.kind}): {subject.summary}\n{subject.detail}".strip()
                ),
            )
        ],
        funding_user_id=resolved.funding_user_id,
    )
    decision = parse_decision(resp.text, {m.user_id for m in members})
    # The model asked for a human but named none we can trust → founder fallback.
    if decision.involve_human and decision.user_id is None:
        f = _founder(members)
        if f is not None:
            decision.user_id = f.user_id
            decision.reason = decision.reason or "human involvement required; routed to founder"
    return decision
