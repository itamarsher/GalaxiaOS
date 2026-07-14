"""Founder decision delegate: a webhook notifier + an opt-in Claude auto-triager.

Two jobs, both hanging off the founder's decision inbox:

1. **Notify (always, when a webhook is set).** Every pending
   :class:`DecisionRequest` is POSTed to the founder's configured ``webhook_url``
   (Slack / Telegram / phone), so "something needs your approval" reaches them
   even with the app closed. Best-effort — a bad webhook never breaks the fleet.

2. **Auto-triage (opt-in).** When ``auto_pilot_enabled`` is on, each new decision
   is run past the company's model (Claude, via the standard provider seam) and
   the *routine* ones are resolved automatically through the SAME
   :func:`app.services.decisions.resolve_decision` path a human click uses — full
   audit trail, task resume, DM note — while everything else is escalated to the
   founder over the webhook.

The delegate can only ever be MORE conservative than the founder: hard, in-code
gates (:func:`_auto_eligible`) decide what is even *eligible* for auto-resolution
before the model is consulted, and the model may still choose to escalate. It can
never approve a kind the founder didn't allow, spend over the cap, or an outbound
external message.

Config lives in a single named :class:`Policy` row with ``effect=allow`` (inert in
the policy engine's ``evaluate`` — see :mod:`app.services.governance`), so it needs
no schema migration and rides the existing tenant-scoped store.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Agent, Company, DecisionRequest, Mission, Policy
from app.models.enums import DecisionKind, DecisionStatus, PolicyEffect, PolicyScope
from app.providers.base import Message
from app.runtime.cost_meter import CostMeter
from app.services import apikeys
from app.services import budget as budget_svc
from app.services import decisions as decisions_svc

#: The named Policy row that carries the delegate config (see module docstring).
DELEGATE_POLICY_NAME = "Founder decision delegate"

#: Kinds a founder may authorise for auto-resolution via the API. ``external_comm``
#: is deliberately absent — an outbound external message is irreversible and always
#: goes to a human. ``strategy`` is open-ended and likewise never auto-resolved.
ALLOWED_AUTO_KINDS: frozenset[str] = frozenset(
    {
        DecisionKind.plan_approval.value,
        DecisionKind.risky_action.value,
        DecisionKind.user_action.value,
        DecisionKind.spend_approval.value,
        DecisionKind.hire_approval.value,
    }
)

#: Kinds that are NEVER auto-resolved regardless of config — the last-line guard.
_NEVER_AUTO: frozenset[str] = frozenset({DecisionKind.external_comm.value})


@dataclass(frozen=True)
class DelegateConfig:
    webhook_url: str | None
    auto_pilot_enabled: bool
    auto_kinds: tuple[str, ...]
    max_auto_spend_cents: int

    @property
    def active(self) -> bool:
        """Whether there's anything to do for this company at all."""
        return bool(self.webhook_url) or self.auto_pilot_enabled


@dataclass(frozen=True)
class DelegateOutcome:
    """What :func:`handle` did with one decision, for the job to act on."""

    disposition: str  # "auto_approved" | "auto_rejected" | "escalated"
    resumed_task_id: uuid.UUID | None
    webhook_payload: dict | None


# ── Config storage (a named, inert Policy row) ────────────────────────────────
async def _config_policy(db: AsyncSession, company_id: uuid.UUID) -> Policy | None:
    return await db.scalar(
        select(Policy).where(
            Policy.company_id == company_id, Policy.name == DELEGATE_POLICY_NAME
        )
    )


def _parse(policy: Policy | None) -> DelegateConfig | None:
    if policy is None:
        return None
    rule = policy.rule or {}
    kinds = tuple(k for k in (rule.get("auto_kinds") or []) if k in ALLOWED_AUTO_KINDS)
    return DelegateConfig(
        webhook_url=(rule.get("webhook_url") or None),
        auto_pilot_enabled=bool(rule.get("auto_pilot_enabled")),
        auto_kinds=kinds,
        max_auto_spend_cents=int(rule.get("max_auto_spend_cents") or 0),
    )


async def get_config(db: AsyncSession, company_id: uuid.UUID) -> DelegateConfig | None:
    return _parse(await _config_policy(db, company_id))


async def set_config(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    webhook_url: str | None,
    auto_pilot_enabled: bool,
    auto_kinds: list[str],
    max_auto_spend_cents: int,
) -> DelegateConfig:
    """Upsert the delegate config. Unknown/forbidden kinds are dropped (never
    silently honoured). Stored with ``effect=allow`` so the policy engine ignores
    it — it's a config carrier, not an action rule."""
    kinds = [k for k in auto_kinds if k in ALLOWED_AUTO_KINDS]
    rule = {
        "webhook_url": (webhook_url or None),
        "auto_pilot_enabled": bool(auto_pilot_enabled),
        "auto_kinds": kinds,
        "max_auto_spend_cents": max(0, int(max_auto_spend_cents)),
    }
    policy = await _config_policy(db, company_id)
    if policy is None:
        policy = Policy(
            company_id=company_id,
            name=DELEGATE_POLICY_NAME,
            scope=PolicyScope.global_,
            rule=rule,
            effect=PolicyEffect.allow,  # inert in governance.evaluate
            priority=1000,
            enabled=True,
        )
        db.add(policy)
    else:
        policy.rule = rule
        policy.effect = PolicyEffect.allow
    await db.flush()
    return _parse(policy)


# ── Eligibility (the hard, in-code guard) ─────────────────────────────────────
def _spend_cents(decision: DecisionRequest) -> int:
    payload = decision.payload or {}
    args = payload.get("args") or {}
    return int(payload.get("amount_cents") or args.get("amount_cents") or 0)


def _auto_eligible(cfg: DelegateConfig, decision: DecisionRequest) -> bool:
    """Whether a decision may even be *considered* for auto-resolution.

    This is the guardrail the model cannot override: it runs before any LLM call.
    """
    kind = decision.kind.value if hasattr(decision.kind, "value") else str(decision.kind)
    if kind in _NEVER_AUTO:
        return False
    if kind not in cfg.auto_kinds:
        return False
    if kind == DecisionKind.spend_approval.value:
        return _spend_cents(decision) <= cfg.max_auto_spend_cents
    return True


# ── Model triage ──────────────────────────────────────────────────────────────
_TRIAGE_SYSTEM = (
    "You are the founder's trusted delegate for their autonomous company's "
    "decision inbox. An agent has asked the founder to approve a specific action. "
    "You may only clear ROUTINE, low-stakes, on-mission, reversible decisions on "
    "the founder's behalf. Decide:\n"
    '- "approve": clearly aligned with the mission, low-risk, and something a '
    "founder would wave through without a second thought.\n"
    '- "reject": clearly off-mission, wasteful, or harmful.\n'
    '- "escalate": anything strategic, ambiguous, novel, expensive, or that a '
    "prudent founder would want to see. When in ANY doubt, escalate.\n"
    "Bias hard toward escalate — you exist to remove noise, not to make judgement "
    "calls the founder would want to make themselves. Give a one-sentence rationale."
)

_TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["approve", "reject", "escalate"]},
        "rationale": {"type": "string"},
    },
    "required": ["verdict", "rationale"],
}


async def _company_context(db: AsyncSession, company_id: uuid.UUID) -> str:
    company = await db.get(Company, company_id)
    mission = (
        await db.get(Mission, company.mission_id)
        if company and company.mission_id
        else None
    )
    budget = await budget_svc.get_active_budget(db, company_id)
    lines = []
    if mission is not None:
        lines.append(f"Mission: {mission.raw_text[:400]}")
    if company is not None and company.playbook:
        lines.append(f"Playbook: {company.playbook[:400]}")
    if budget is not None:
        lines.append(
            f"Budget: {budget.spent_cents}c spent / {budget.limit_cents}c limit."
        )
    return "\n".join(lines) or "(no additional company context)"


async def _triage(
    db: AsyncSession, *, company_id: uuid.UUID, decision: DecisionRequest
) -> tuple[str, str | None]:
    """Ask the company's model to approve/reject/escalate. Any failure → escalate,
    so the founder never loses a decision to a provider hiccup."""
    resolved = await apikeys.resolve_active_provider(db, company_id=company_id)
    if resolved is None:
        return "escalate", None
    context = await _company_context(db, company_id)
    meter = CostMeter(SessionLocal)
    try:
        resp = await meter.run_llm(
            resolved.provider,
            api_key=resolved.api_key,
            company_id=company_id,
            agent_id=None,
            task_id=None,
            model=resolved.provider.default_models["cheap"],
            system=_TRIAGE_SYSTEM,
            messages=[
                Message(
                    role="user",
                    content=(
                        f"Company context:\n{context}\n\n"
                        f"Decision the agent is asking the founder to approve "
                        f"({decision.kind.value}):\n{decision.summary}"
                    ),
                )
            ],
            max_tokens=200,
            json_schema=_TRIAGE_SCHEMA,
            funding_user_id=resolved.funding_user_id,
        )
        data = json.loads(resp.text)
        verdict = data.get("verdict")
        rationale = (data.get("rationale") or "").strip()[:400] or None
    except Exception:
        return "escalate", None
    if verdict not in ("approve", "reject"):
        return "escalate", rationale
    return verdict, rationale


# ── Handling one decision ─────────────────────────────────────────────────────
async def untriaged_pending(
    db: AsyncSession, company_id: uuid.UUID, limit: int = 50
) -> list[DecisionRequest]:
    """Pending decisions the delegate hasn't looked at yet (no ``delegate`` marker),
    that have an agent/DM to answer in."""
    rows = await db.scalars(
        select(DecisionRequest)
        .where(
            DecisionRequest.company_id == company_id,
            DecisionRequest.status == DecisionStatus.pending,
            DecisionRequest.agent_id.isnot(None),
            DecisionRequest.payload["delegate"].is_(None),
        )
        .order_by(DecisionRequest.created_at.asc())
        .limit(limit)
    )
    return list(rows.all())


async def _webhook_payload(
    db: AsyncSession, *, company: Company, decision: DecisionRequest, disposition: str, rationale: str | None
) -> dict:
    agent = await db.get(Agent, decision.agent_id) if decision.agent_id else None
    web = settings.web_base_url.rstrip("/") if settings.web_base_url else ""
    api = settings.public_api_base_url.rstrip("/") if settings.public_api_base_url else ""
    base = f"/companies/{company.id}/decisions/{decision.id}"
    return {
        "type": "founder_decision",
        "disposition": disposition,
        "needs_you": disposition == "escalated",
        "company_id": str(company.id),
        "company_name": company.name,
        "decision_id": str(decision.id),
        "kind": decision.kind.value,
        "agent": agent.name if agent else None,
        "agent_role": agent.role.value if agent else None,
        "summary": decision.summary,
        "delegate_rationale": rationale,
        "inbox_url": f"{web}/c/{company.id}" if web else None,
        "approve_url": f"{api}{base}/approve" if api else None,
        "reject_url": f"{api}{base}/reject" if api else None,
    }


async def handle(
    db: AsyncSession, *, company: Company, decision: DecisionRequest, cfg: DelegateConfig
) -> DelegateOutcome:
    """Triage one pending decision. Resolves it in-session when auto-pilot clears
    it, else marks it escalated; either way stamps a ``delegate`` marker so it's
    handled exactly once. Returns the resumed task id (to enqueue) and the webhook
    payload (to POST) for the caller to fire AFTER commit."""
    disposition = "escalated"
    rationale: str | None = None
    resumed: uuid.UUID | None = None

    if cfg.auto_pilot_enabled and _auto_eligible(cfg, decision):
        verdict, rationale = await _triage(db, company_id=company.id, decision=decision)
        if verdict in ("approve", "reject"):
            approved = verdict == "approve"
            disposition = "auto_approved" if approved else "auto_rejected"
            note = (
                f"Auto-{'approved' if approved else 'rejected'} by your Claude "
                f"delegate. {rationale or ''}"
            ).strip()
            resumed = await decisions_svc.resolve_decision(
                db, decision, approved=approved, user_id=None, note=note
            )

    # Stamp the marker so the triage cron never touches this decision twice (an
    # escalated one stays pending, so without this it would re-notify every run).
    decision.payload = {
        **(decision.payload or {}),
        "delegate": {"disposition": disposition, "rationale": rationale},
    }
    await db.flush()

    payload = None
    if cfg.webhook_url:
        payload = await _webhook_payload(
            db, company=company, decision=decision, disposition=disposition, rationale=rationale
        )
    return DelegateOutcome(disposition=disposition, resumed_task_id=resumed, webhook_payload=payload)


async def send_webhook(url: str, payload: dict) -> bool:
    """POST a payload to the founder's webhook. Best-effort: any failure is
    swallowed (a broken webhook must never disrupt the fleet). Returns success."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, json=payload)
        return resp.status_code < 400
    except Exception:
        return False
