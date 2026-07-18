"""Founder decision delegate: notification webhooks + involvement-based routing.

Two jobs, both hanging off the founder's decision inbox:

1. **Notify.** Every pending :class:`DecisionRequest` is POSTed to the founder's
   configured notification webhooks (Slack / Telegram / phone), so "something
   needs your approval" reaches them even with the app closed. Each webhook picks
   which dispositions it wants (all / escalations-only / auto-handled-only), and
   every request is **HMAC-signed** with the company's signing secret so the
   receiver can verify it genuinely came from ABOS (spoof protection). Best-effort
   — a bad webhook never breaks the fleet.

2. **Route.** Who (if anyone) should own a pending decision is decided by the
   :mod:`app.services.involvement_router` — per-person, founder-sanctioned
   involvement prose — NOT by an old company-wide autonomy slider (removed). For
   each pending decision:

   - the router names a **human** to involve → the decision is **escalated**
     (left pending, the owner recorded), and the founder's webhooks fire;
   - the router involves **no one** → the decision is **auto-approved** so the
     agents proceed autonomously. The Budget hard-cap still bounds spend
     downstream, and the external-communication approval guardrail (below) still
     forces a human when it is on.

   The one hard override: an ``external_comm`` decision is **always escalated**
   while the company's external-comms approval guardrail is enabled, regardless of
   what the router says — an explicit founder guardrail is never auto-cleared.

Config lives in one inert :class:`Policy` row (``effect=allow`` — ignored by
``governance.evaluate``), so it needs no schema migration and rides the existing
tenant-scoped store. It now carries only the notification settings (webhooks,
signing secret, Telegram link); involvement prose lives on the memberships. The
separate governance policy engine (what *becomes* a decision) is unchanged and
orthogonal to this.
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
from app.models import Agent, Company, DecisionRequest, Policy
from app.models.enums import (
    DecisionKind,
    DecisionStatus,
    PolicyEffect,
    PolicyScope,
)
from app.services import decisions as decisions_svc
from app.services import governance as governance_svc
from app.services import involvement_router

#: The named Policy row that carries the delegate config (see module docstring).
DELEGATE_POLICY_NAME = "Founder decision delegate"

#: Per-webhook event filter: which dispositions a notification URL wants.
WEBHOOK_EVENTS: frozenset[str] = frozenset({"all", "escalations", "auto_handled"})

#: The founder may configure at most this many notification webhooks.
MAX_WEBHOOKS = 3


@dataclass(frozen=True)
class WebhookTarget:
    url: str
    events: str  # one of WEBHOOK_EVENTS


@dataclass(frozen=True)
class DelegateConfig:
    """The founder's NOTIFICATION settings (routing itself is prose-driven)."""

    webhooks: tuple[WebhookTarget, ...]
    signing_secret: str | None
    #: The founder's linked Telegram chat (shared platform bot), if connected.
    telegram_chat_id: str | None = None
    telegram_events: str = "all"  # one of WEBHOOK_EVENTS

    @property
    def has_targets(self) -> bool:
        """Whether there's any channel to notify (webhooks or Telegram)."""
        return bool(self.webhooks) or bool(self.telegram_chat_id)


@dataclass(frozen=True)
class DelegateOutcome:
    disposition: str  # "auto_approved" | "escalated"
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
    webhooks: list[dict] | None = None,
    rotate_secret: bool = False,
    telegram_events: str | None = None,
) -> DelegateConfig:
    """Partial-update the delegate's NOTIFICATION config: only the fields you pass
    change, the rest are preserved. Invalid webhooks are normalised. A signing
    secret is minted the first time a webhook is set (spoof protection on by
    default) and rotatable on demand. The Telegram connection (chat id) is linked
    from Telegram, never here. Stored with ``effect=allow`` so the policy engine
    ignores the row."""
    policy = await _config_policy(db, company_id)
    prev = (policy.rule or {}) if policy else {}

    if webhooks is None:
        targets = prev.get("webhooks") or []
    else:
        targets = [
            {"url": w["url"], "events": (w.get("events") or "all")}
            for w in webhooks
            if isinstance(w, dict)
            and w.get("url")
            and (w.get("events") or "all") in WEBHOOK_EVENTS
        ][:MAX_WEBHOOKS]

    existing_secret = prev.get("signing_secret")
    secret = existing_secret
    if rotate_secret or (targets and not existing_secret):
        secret = secrets.token_hex(32)
    tg_events = telegram_events if telegram_events in WEBHOOK_EVENTS else (
        prev.get("telegram_events") or "all"
    )

    rule = {
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
            rule={"webhooks": [], **patch},
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


async def company_for_telegram_chat(
    db: AsyncSession, chat_id: str
) -> uuid.UUID | None:
    """The company whose delegate config is linked to this Telegram chat, if any.

    Reverse of :func:`link_telegram` — lets the inbound webhook route a founder's
    reply back to their company. Must be called on a session with NO tenant set
    (the sender's company is unknown until this resolves), so it sees across
    tenants; the caller then scopes to the returned company."""
    return await db.scalar(
        select(Policy.company_id).where(
            Policy.name == DELEGATE_POLICY_NAME,
            Policy.rule["telegram_chat_id"].astext == str(chat_id),
        )
    )


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
    db: AsyncSession,
    *,
    company: Company,
    decision: DecisionRequest,
    disposition: str,
    rationale: str | None,
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
    cfg: DelegateConfig | None = None,
) -> DelegateOutcome:
    """Route one pending decision by human involvement (see module docstring).

    Escalates to the involvement owner (or the founder, per the router's fail-safe),
    else auto-approves so agents proceed. An ``external_comm`` is always escalated
    while the external-comms approval guardrail is on. Either way stamps a
    ``delegate`` marker so it's handled exactly once. Returns the resumed task id
    (to enqueue) and the base webhook payload (to sign + POST) for the caller to
    fire AFTER commit."""
    routed_to: uuid.UUID | None = None
    resumed: uuid.UUID | None = None

    # Hard override: an explicit external-comms guardrail always wants a human.
    if decision.kind == DecisionKind.external_comm and await (
        governance_svc.get_external_comms_approval(db, company_id=company.id)
    ):
        disposition = "escalated"
        rationale: str | None = "external-communication approval guardrail is on"
    else:
        d = await involvement_router.route(
            db,
            company_id=company.id,
            subject=involvement_router.RoutingSubject(
                kind=decision.kind.value, summary=decision.summary
            ),
        )
        rationale = d.reason or None
        if d.involve_human:
            disposition = "escalated"
            routed_to = d.user_id
        else:
            disposition = "auto_approved"
            note = (
                "Auto-approved by your delegate: no teammate opted into this kind "
                f"of decision. {rationale or ''}"
            ).strip()
            resumed = await decisions_svc.resolve_decision(
                db, decision, approved=True, user_id=None, note=note
            )

    # Stamp the marker so the triage cron never touches this decision twice (an
    # escalated one stays pending, so without this it would re-notify every run).
    decision.payload = {
        **(decision.payload or {}),
        "delegate": {
            "disposition": disposition,
            "rationale": rationale,
            "routed_to": str(routed_to) if routed_to else None,
        },
    }
    await db.flush()

    payload = None
    if cfg is not None and cfg.has_targets:
        payload = await _webhook_payload(
            db,
            company=company,
            decision=decision,
            disposition=disposition,
            rationale=rationale,
        )
    return DelegateOutcome(
        disposition=disposition, resumed_task_id=resumed, webhook_payload=payload
    )


# ── Webhook delivery (signed) ─────────────────────────────────────────────────
def webhook_wants(events: str, disposition: str) -> bool:
    """Whether a webhook configured for ``events`` should receive this disposition."""
    if events == "all":
        return True
    if events == "escalations":
        return disposition == "escalated"
    if events == "auto_handled":
        return disposition == "auto_approved"
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
