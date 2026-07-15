"""Founder decision delegate: notification webhooks + a Claude auto-triager whose
reach is set by a single company-wide autonomy slider.

Two jobs, both hanging off the founder's decision inbox:

1. **Notify.** Every pending :class:`DecisionRequest` is POSTed to the founder's
   configured notification webhooks (Slack / Telegram / phone), so "something
   needs your approval" reaches them even with the app closed. Each webhook picks
   which dispositions it wants (all / escalations-only / auto-handled-only), and
   every request is **HMAC-signed** with the company's signing secret so the
   receiver can verify it genuinely came from ABOS (spoof protection). Best-effort
   — a bad webhook never breaks the fleet.

2. **Auto-triage.** The **autonomy level** (:class:`DelegateAutonomy`, 1–4) decides
   how much the delegate resolves on the founder's behalf:

   - **1 manual** — nothing is auto-resolved; every decision escalates.
   - **2 assisted** — auto-handle plans + low-stakes confirmations; never spend.
   - **3 supervised** — + minor expenditures within a cap; more autonomy.
   - **4 autonomous** — fully autonomous within budget; escalate only *extreme*
     spend (large in absolute terms or relative to remaining budget).

   Eligible decisions are run past the company's model and the routine ones are
   resolved through the SAME :func:`app.services.decisions.resolve_decision` path a
   human click uses (full audit trail, task resume, DM note); everything else is
   escalated over the webhooks.

The delegate can only ever be MORE conservative than the level: a hard, in-code
gate (:func:`_auto_eligible`) decides eligibility BEFORE any model call, and the
model may still choose to escalate. Config lives in one inert :class:`Policy` row
(``effect=allow`` — ignored by ``governance.evaluate``), so it needs no schema
migration and rides the existing tenant-scoped store. The separate governance
policy engine (what *becomes* a decision) is unchanged and orthogonal to this.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import SessionLocal
from app.models import Agent, Company, DecisionRequest, Mission, Policy
from app.models.enums import (
    DecisionKind,
    DecisionStatus,
    DelegateAutonomy,
    PolicyEffect,
    PolicyScope,
)
from app.providers.base import Message
from app.runtime.cost_meter import CostMeter
from app.services import apikeys
from app.services import budget as budget_svc
from app.services import decisions as decisions_svc

#: The named Policy row that carries the delegate config (see module docstring).
DELEGATE_POLICY_NAME = "Founder decision delegate"

#: Per-webhook event filter: which dispositions a notification URL wants.
WEBHOOK_EVENTS: frozenset[str] = frozenset({"all", "escalations", "auto_handled"})

#: The founder may configure at most this many notification webhooks.
MAX_WEBHOOKS = 3

# ── Autonomy levels → what the delegate is allowed to auto-resolve ────────────
_LOW_STAKES = frozenset(
    {
        DecisionKind.plan_approval.value,
        DecisionKind.risky_action.value,
        DecisionKind.user_action.value,
    }
)
_WITH_SPEND = _LOW_STAKES | {DecisionKind.spend_approval.value}
_EVERYTHING = _WITH_SPEND | {
    DecisionKind.hire_approval.value,
    DecisionKind.external_comm.value,
}


@dataclass(frozen=True)
class LevelPolicy:
    """What one autonomy level lets the delegate do — the hard, in-code gate."""

    enabled: bool  # False at level 1: nothing auto-resolves
    auto_kinds: frozenset[str]  # decision kinds eligible for auto-resolution
    spend_cap_cents: int | None  # per-decision spend ceiling; None = within-budget
    extreme_cents: int  # level 4: escalate spend at/over this absolute floor…
    extreme_fraction: float  # …or over this fraction of remaining budget


def level_policy(level: int) -> LevelPolicy:
    """Map an autonomy level (1–4) to its concrete permissions."""
    if level <= DelegateAutonomy.manual.value:
        return LevelPolicy(False, frozenset(), 0, 0, 0.0)
    if level == DelegateAutonomy.assisted.value:
        return LevelPolicy(True, _LOW_STAKES, 0, 0, 0.0)
    if level == DelegateAutonomy.supervised.value:
        return LevelPolicy(True, _WITH_SPEND, settings.delegate_l3_spend_cap_cents, 0, 0.0)
    # autonomous: everything eligible, spend gated only by "extreme" thresholds.
    return LevelPolicy(
        True,
        _EVERYTHING,
        None,
        settings.delegate_l4_extreme_cents,
        settings.delegate_l4_extreme_fraction,
    )


@dataclass(frozen=True)
class WebhookTarget:
    url: str
    events: str  # one of WEBHOOK_EVENTS


@dataclass(frozen=True)
class DelegateConfig:
    autonomy_level: int
    webhooks: tuple[WebhookTarget, ...]
    signing_secret: str | None
    #: The founder's linked Telegram chat (shared platform bot), if connected.
    telegram_chat_id: str | None = None
    telegram_events: str = "all"  # one of WEBHOOK_EVENTS

    @property
    def active(self) -> bool:
        """Whether there's anything for the triage cron to do."""
        return (
            self.autonomy_level >= DelegateAutonomy.assisted.value
            or bool(self.webhooks)
            or bool(self.telegram_chat_id)
        )


@dataclass(frozen=True)
class DelegateOutcome:
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

    # Autonomy level, clamped to the valid range. Migrate pre-slider configs: an
    # old auto-pilot-on row maps to "assisted", else "manual".
    if "autonomy_level" in rule:
        level = max(1, min(4, int(rule.get("autonomy_level") or 1)))
    else:
        level = DelegateAutonomy.assisted.value if rule.get("auto_pilot_enabled") else 1

    # Webhooks. Migrate the old single `webhook_url` into the new list shape.
    raw = rule.get("webhooks")
    if raw is None and rule.get("webhook_url"):
        raw = [{"url": rule["webhook_url"], "events": "all"}]
    webhooks = tuple(
        WebhookTarget(url=w["url"], events=(w.get("events") or "all"))
        for w in (raw or [])
        if isinstance(w, dict)
        and w.get("url")
        and (w.get("events") or "all") in WEBHOOK_EVENTS
    )[:MAX_WEBHOOKS]

    tg_events = rule.get("telegram_events") or "all"
    return DelegateConfig(
        autonomy_level=level,
        webhooks=webhooks,
        signing_secret=(rule.get("signing_secret") or None),
        telegram_chat_id=(rule.get("telegram_chat_id") or None),
        telegram_events=(tg_events if tg_events in WEBHOOK_EVENTS else "all"),
    )


async def get_config(db: AsyncSession, company_id: uuid.UUID) -> DelegateConfig | None:
    return _parse(await _config_policy(db, company_id))


async def set_config(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    autonomy_level: int,
    webhooks: list[dict],
    rotate_secret: bool = False,
    telegram_events: str | None = None,
) -> DelegateConfig:
    """Upsert the delegate config. Invalid webhooks/levels are normalised, never
    silently honoured. A signing secret is minted the first time a webhook is set
    (so spoof protection is on by default) and can be rotated on demand. The
    Telegram *connection* (chat id) is preserved across saves — it's linked from
    Telegram, not from this form. Stored with ``effect=allow`` so the policy engine
    ignores the row."""
    level = max(1, min(4, int(autonomy_level)))
    targets = [
        {"url": w["url"], "events": (w.get("events") or "all")}
        for w in (webhooks or [])
        if isinstance(w, dict)
        and w.get("url")
        and (w.get("events") or "all") in WEBHOOK_EVENTS
    ][:MAX_WEBHOOKS]

    policy = await _config_policy(db, company_id)
    prev = (policy.rule or {}) if policy else {}
    existing_secret = prev.get("signing_secret")
    secret = existing_secret
    if rotate_secret or (targets and not existing_secret):
        secret = secrets.token_hex(32)
    tg_events = telegram_events if telegram_events in WEBHOOK_EVENTS else (
        prev.get("telegram_events") or "all"
    )

    rule = {
        "autonomy_level": level,
        "webhooks": targets,
        "signing_secret": secret,
        "telegram_chat_id": prev.get("telegram_chat_id") or None,
        "telegram_events": tg_events,
    }
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


async def _upsert_rule(db: AsyncSession, company_id: uuid.UUID, patch: dict) -> None:
    """Merge ``patch`` into the delegate policy row (creating it if needed)."""
    policy = await _config_policy(db, company_id)
    if policy is None:
        policy = Policy(
            company_id=company_id,
            name=DELEGATE_POLICY_NAME,
            scope=PolicyScope.global_,
            rule={"autonomy_level": 1, "webhooks": [], **patch},
            effect=PolicyEffect.allow,
            priority=1000,
            enabled=True,
        )
        db.add(policy)
    else:
        policy.rule = {**(policy.rule or {}), **patch}
    await db.flush()


async def link_telegram(
    db: AsyncSession, *, company_id: uuid.UUID, chat_id: str
) -> None:
    """Attach a founder's Telegram chat to a company (from the /start deep link)."""
    await _upsert_rule(db, company_id, {"telegram_chat_id": str(chat_id)})


async def unlink_telegram(db: AsyncSession, *, company_id: uuid.UUID) -> None:
    await _upsert_rule(db, company_id, {"telegram_chat_id": None})


# ── Eligibility (the hard, in-code guard) ─────────────────────────────────────
def _spend_cents(decision: DecisionRequest) -> int:
    payload = decision.payload or {}
    args = payload.get("args") or {}
    return int(payload.get("amount_cents") or args.get("amount_cents") or 0)


def _extreme_spend_floor(policy: LevelPolicy, remaining_budget_cents: int | None) -> int:
    """Above this, a level-4 spend is 'extreme' and escalates to the founder."""
    by_fraction = int((remaining_budget_cents or 0) * policy.extreme_fraction)
    return max(policy.extreme_cents, by_fraction)


def _auto_eligible(
    cfg: DelegateConfig,
    decision: DecisionRequest,
    remaining_budget_cents: int | None = None,
) -> bool:
    """Whether a decision may even be *considered* for auto-resolution.

    Runs before any LLM call — the model cannot widen this. Spend is gated by the
    level: a fixed cap below level 4, and an "extreme" threshold at level 4 (the
    actual budget ceiling is separately enforced downstream by ``CostMeter``)."""
    policy = level_policy(cfg.autonomy_level)
    if not policy.enabled:
        return False
    kind = decision.kind.value if hasattr(decision.kind, "value") else str(decision.kind)
    if kind not in policy.auto_kinds:
        return False
    if kind == DecisionKind.spend_approval.value:
        amount = _spend_cents(decision)
        if policy.spend_cap_cents is not None:
            return amount <= policy.spend_cap_cents
        return amount < _extreme_spend_floor(policy, remaining_budget_cents)
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
    # Decision resolve endpoints are mounted at /decisions/{id}/{approve,reject}
    # (no /companies prefix — see app.api.decisions).
    base = f"/decisions/{decision.id}"
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
    db: AsyncSession,
    *,
    company: Company,
    decision: DecisionRequest,
    cfg: DelegateConfig,
    remaining_budget_cents: int | None = None,
) -> DelegateOutcome:
    """Triage one pending decision. Resolves it in-session when the autonomy level
    clears it, else marks it escalated; either way stamps a ``delegate`` marker so
    it's handled exactly once. Returns the resumed task id (to enqueue) and the
    base webhook payload (to sign + POST) for the caller to fire AFTER commit."""
    disposition = "escalated"
    rationale: str | None = None
    resumed: uuid.UUID | None = None

    if _auto_eligible(cfg, decision, remaining_budget_cents):
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
    if cfg.webhooks or cfg.telegram_chat_id:
        payload = await _webhook_payload(
            db, company=company, decision=decision, disposition=disposition, rationale=rationale
        )
    return DelegateOutcome(disposition=disposition, resumed_task_id=resumed, webhook_payload=payload)


# ── Webhook delivery (signed) ─────────────────────────────────────────────────
def webhook_wants(events: str, disposition: str) -> bool:
    """Whether a webhook configured for ``events`` should receive this disposition."""
    if events == "all":
        return True
    if events == "escalations":
        return disposition == "escalated"
    if events == "auto_handled":
        return disposition in ("auto_approved", "auto_rejected")
    return False


def sign_payload(secret: str, timestamp: str, body: str) -> str:
    """HMAC-SHA256 over ``"{timestamp}.{body}"`` — the receiver recomputes this to
    prove the request came from ABOS (and isn't replayed via the timestamp)."""
    mac = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


async def send_webhook(url: str, payload: dict, secret: str | None = None) -> bool:
    """POST a payload to a founder webhook, HMAC-signed when a secret is set.
    Best-effort: any failure is swallowed (a broken webhook must never disrupt the
    fleet). Returns success."""
    body = json.dumps(payload, separators=(",", ":"))
    headers = {"Content-Type": "application/json"}
    if secret:
        ts = str(int(datetime.now(UTC).timestamp()))
        headers["X-Abos-Timestamp"] = ts
        headers["X-Abos-Signature"] = sign_payload(secret, ts, body)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(url, content=body, headers=headers)
        return resp.status_code < 400
    except Exception:
        return False
