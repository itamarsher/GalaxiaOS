"""Founder decision delegate: involvement-based routing, notification config +
signed webhooks, auto-approve / escalation, and the handled-once marker."""

from __future__ import annotations

import uuid

from app.models import Agent, AgentRun, Company, DecisionRequest, Membership, Policy, Task, User
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    MembershipRole,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.services import chat, involvement_router
from app.services import delegate as dlg
from tests.conftest import requires_db


def _cfg(webhooks=(), secret=None):
    return dlg.DelegateConfig(
        webhooks=tuple(dlg.WebhookTarget(u, e) for u, e in webhooks),
        signing_secret=secret,
    )


# ── pure notification helpers ────────────────────────────────────────────────
def test_webhook_wants_filters_by_disposition():
    assert dlg.webhook_wants("all", "escalated") is True
    assert dlg.webhook_wants("all", "auto_approved") is True
    assert dlg.webhook_wants("escalations", "escalated") is True
    assert dlg.webhook_wants("escalations", "auto_approved") is False
    assert dlg.webhook_wants("auto_handled", "auto_approved") is True
    assert dlg.webhook_wants("auto_handled", "escalated") is False


def test_sign_payload_is_stable_hmac():
    sig = dlg.sign_payload("shhh", "1700000000", '{"a":1}')
    assert sig.startswith("sha256=")
    assert sig == dlg.sign_payload("shhh", "1700000000", '{"a":1}')
    assert sig != dlg.sign_payload("shhh", "1700000000", '{"a":2}')


async def test_send_webhook_is_best_effort():
    assert await dlg.send_webhook("http://127.0.0.1:9/nope", {"x": 1}, secret="s") is False


# ── notification config ──────────────────────────────────────────────────────
@requires_db
async def test_set_config_mints_and_rotates_secret(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        # A webhook auto-mints a signing secret (spoof protection on by default).
        cfg = await dlg.set_config(
            db,
            company_id=company_id,
            webhooks=[{"url": "https://hooks.example.com/a", "events": "escalations"},
                      {"url": "https://hooks.example.com/b", "events": "bogus"}],  # bogus filtered out
            rotate_secret=False,
        )
        await db.commit()
    # The bogus-events entry is filtered out; the valid one survives.
    assert len(cfg.webhooks) == 1 and cfg.webhooks[0].events == "escalations"
    first_secret = cfg.signing_secret
    assert first_secret and len(first_secret) >= 32

    async with session_factory() as db:
        again = await dlg.get_config(db, company_id)
    assert again.signing_secret == first_secret  # stable across reads

    async with session_factory() as db:
        rotated = await dlg.set_config(
            db, company_id=company_id,
            webhooks=[{"url": "https://hooks.example.com/a", "events": "all"}],
            rotate_secret=True,
        )
        await db.commit()
    assert rotated.signing_secret != first_secret


@requires_db
async def test_set_config_partial_updates_are_independent(session_factory, company_with_budget):
    """Notification slices save independently: changing the webhooks must leave the
    secret and Telegram link alone, and an empty list explicitly clears them."""
    company_id = company_with_budget
    async with session_factory() as db:
        await dlg.set_config(
            db,
            company_id=company_id,
            webhooks=[{"url": "https://hooks.example.com/a", "events": "all"}],
        )
        await db.commit()
    async with session_factory() as db:
        seeded = await dlg.get_config(db, company_id)
    secret = seeded.signing_secret
    assert len(seeded.webhooks) == 1 and secret

    # Change only the webhooks — the secret must survive untouched.
    async with session_factory() as db:
        after_hooks = await dlg.set_config(
            db,
            company_id=company_id,
            webhooks=[{"url": "https://hooks.example.com/b", "events": "escalations"}],
        )
        await db.commit()
    assert [(w.url, w.events) for w in after_hooks.webhooks] == [
        ("https://hooks.example.com/b", "escalations")
    ]
    assert after_hooks.signing_secret == secret

    # Passing an empty list explicitly clears the webhooks (distinct from None).
    async with session_factory() as db:
        cleared = await dlg.set_config(db, company_id=company_id, webhooks=[])
        await db.commit()
    assert cleared.webhooks == ()


@requires_db
async def test_parse_migrates_legacy_webhook_url(session_factory, company_with_budget):
    """An old pre-slider row (single webhook_url) reads with the URL migrated into
    the webhook list; the dropped autonomy_level is simply ignored."""
    company_id = company_with_budget
    async with session_factory() as db:
        from app.models.enums import PolicyEffect, PolicyScope

        db.add(
            Policy(
                company_id=company_id,
                name=dlg.DELEGATE_POLICY_NAME,
                scope=PolicyScope.global_,
                rule={
                    "autonomy_level": 4,  # legacy field — ignored now
                    "webhook_url": "https://old.example.com/hook",
                },
                effect=PolicyEffect.allow,
                priority=1000,
            )
        )
        await db.commit()
    async with session_factory() as db:
        cfg = await dlg.get_config(db, company_id)
    assert [w.url for w in cfg.webhooks] == ["https://old.example.com/hook"]


# ── routing one decision ─────────────────────────────────────────────────────
async def _founder_membership(session_factory, company_id, *, involvement=None):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        db.add(Membership(user_id=user.id, company_id=company_id,
                          role=MembershipRole.founder, involvement=involvement))
        await db.commit()
        return user.id


async def _pending_decision(session_factory, company_id, *, kind, payload):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add(agent)
        await db.flush()
        run = AgentRun(company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(company_id=company_id, run_id=run.id, root_run_id=run.id,
                    agent_id=agent.id, goal="g", status=TaskStatus.waiting_approval)
        db.add(task)
        await db.flush()
        decision = DecisionRequest(
            company_id=company_id, agent_id=agent.id, task_id=task.id,
            kind=kind, summary="please approve", payload=payload, status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.flush()
        await chat.attach_decision_dm(db, decision=decision)
        await db.commit()
        return task.id, decision.id


@requires_db
async def test_handle_auto_approves_when_no_one_is_involved(
    session_factory, company_with_budget, monkeypatch
):
    """With no member opting into this decision kind, the router involves no human
    and the delegate auto-approves so agents proceed — the task resumes."""
    company_id = company_with_budget
    from app.services import decisions as decisions_svc

    async def _noop_write(*a, **k):
        return None

    monkeypatch.setattr(decisions_svc.memory_svc, "write", _noop_write)
    monkeypatch.setattr(dlg.settings, "public_api_base_url", "https://api.test")

    # Router: no stated involvement → autonomous (no LLM/provider needed).
    async def _autonomous(*a, **k):
        return involvement_router.RoutingDecision(involve_human=False, reason="nobody opted in")

    monkeypatch.setattr(dlg.involvement_router, "route", _autonomous)

    task_id, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.plan_approval, payload={"tool": "submit_plan"}
    )
    cfg = _cfg([("https://hooks.example.com/x", "all")], secret="sek")
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        decision = await db.get(DecisionRequest, decision_id)
        outcome = await dlg.handle(db, company=company, decision=decision, cfg=cfg)
        await db.commit()

    assert outcome.disposition == "auto_approved"
    assert outcome.resumed_task_id == task_id
    assert outcome.webhook_payload["approve_url"].endswith(f"/decisions/{decision_id}/approve")
    async with session_factory() as db:
        d = await db.get(DecisionRequest, decision_id)
        assert d.status is DecisionStatus.approved
        assert d.payload.get("delegate", {}).get("disposition") == "auto_approved"
        t = await db.get(Task, task_id)
        assert t.status is TaskStatus.queued


@requires_db
async def test_handle_escalates_to_the_involved_human(
    session_factory, company_with_budget, monkeypatch
):
    """When the router names a human to own the decision, it is escalated: left
    pending, the owner recorded, and the webhook flags needs_you."""
    company_id = company_with_budget
    owner_id = uuid.uuid4()

    async def _involve(*a, **k):
        return involvement_router.RoutingDecision(
            involve_human=True, user_id=owner_id, reason="founder wants spend sign-off"
        )

    monkeypatch.setattr(dlg.involvement_router, "route", _involve)

    _t, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.spend_approval,
        payload={"tool": "register_domain", "amount_cents": 1200},
    )
    cfg = _cfg([("https://hooks.example.com/x", "all")], secret="sek")
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        decision = await db.get(DecisionRequest, decision_id)
        outcome = await dlg.handle(db, company=company, decision=decision, cfg=cfg)
        await db.commit()

    assert outcome.disposition == "escalated"
    assert outcome.resumed_task_id is None
    assert outcome.webhook_payload["needs_you"] is True
    async with session_factory() as db:
        d = await db.get(DecisionRequest, decision_id)
        assert d.status is DecisionStatus.pending
        marker = d.payload.get("delegate", {})
        assert marker.get("disposition") == "escalated"
        assert marker.get("routed_to") == str(owner_id)


@requires_db
async def test_external_comms_guardrail_forces_escalation(
    session_factory, company_with_budget, monkeypatch
):
    """The external-comms approval guardrail is a hard override: an external_comm
    decision escalates even when the router would otherwise auto-approve."""
    company_id = company_with_budget
    from app.services import governance as governance_svc

    async with session_factory() as db:
        await governance_svc.set_external_comms_approval(db, company_id=company_id, enabled=True)
        await db.commit()

    # Router would auto-approve — the guardrail must win regardless.
    async def _autonomous(*a, **k):
        raise AssertionError("router must not be consulted when the guardrail forces escalation")

    monkeypatch.setattr(dlg.involvement_router, "route", _autonomous)

    _t, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.external_comm, payload={"tool": "send_email"}
    )
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        decision = await db.get(DecisionRequest, decision_id)
        outcome = await dlg.handle(db, company=company, decision=decision, cfg=None)
        await db.commit()

    assert outcome.disposition == "escalated"
    async with session_factory() as db:
        d = await db.get(DecisionRequest, decision_id)
        assert d.status is DecisionStatus.pending


@requires_db
async def test_untriaged_pending_excludes_already_handled(session_factory, company_with_budget):
    company_id = company_with_budget
    _t, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.plan_approval, payload={}
    )
    async with session_factory() as db:
        assert any(d.id == decision_id for d in await dlg.untriaged_pending(db, company_id))
        d = await db.get(DecisionRequest, decision_id)
        d.payload = {**(d.payload or {}), "delegate": {"disposition": "escalated"}}
        await db.commit()
    async with session_factory() as db:
        assert all(d.id != decision_id for d in await dlg.untriaged_pending(db, company_id))


# ── Telegram plumbing (unchanged by the routing rework) ──────────────────────
@requires_db
async def test_telegram_link_survives_settings_save(session_factory, company_with_budget):
    """Linking Telegram is preserved across a Settings PUT (webhooks only), and
    unlinking clears it."""
    company_id = company_with_budget
    async with session_factory() as db:
        await dlg.link_telegram(db, company_id=company_id, chat_id="12345")
        await db.commit()
    async with session_factory() as db:
        cfg = await dlg.get_config(db, company_id)
        assert cfg.telegram_chat_id == "12345" and cfg.has_targets is True

    async with session_factory() as db:
        cfg = await dlg.set_config(
            db, company_id=company_id, webhooks=[], telegram_events="escalations"
        )
        await db.commit()
    assert cfg.telegram_chat_id == "12345"
    assert cfg.telegram_events == "escalations"

    async with session_factory() as db:
        await dlg.unlink_telegram(db, company_id=company_id)
        await db.commit()
        cfg = await dlg.get_config(db, company_id)
    assert cfg.telegram_chat_id is None


def test_telegram_connect_token_is_deeplink_safe():
    import re

    from app.security import create_telegram_connect_token, decode_telegram_connect_token

    cid = uuid.uuid4()
    tok = create_telegram_connect_token(cid)
    assert len(tok) <= 64
    assert re.fullmatch(r"[A-Za-z0-9_-]+", tok)
    assert decode_telegram_connect_token(tok) == cid
    assert decode_telegram_connect_token("garbage") is None
    assert decode_telegram_connect_token(create_telegram_connect_token(cid, minutes=-1)) is None


def test_telegram_format_decision():
    from app.services import telegram

    needs = telegram.format_decision(
        {"needs_you": True, "company_name": "Acme", "kind": "spend_approval",
         "agent": "CEO", "summary": "Buy a domain", "inbox_url": "https://x/c/1"}
    )
    assert "Needs your approval" in needs and "Acme" in needs and "https://x/c/1" in needs
    handled = telegram.format_decision(
        {"needs_you": False, "company_name": "Acme", "kind": "plan_approval",
         "agent": "CEO", "summary": "ok", "delegate_rationale": "routine"}
    )
    assert "Handled" in handled and "routine" in handled


def test_telegram_format_decision_escapes_agent_markdown():
    from app.services import telegram

    out = telegram.format_decision(
        {
            "needs_you": True,
            "company_name": "A & B <Co>",
            "kind": "plan_approval",
            "agent": "Growth Lead",
            "summary": "## Objective 3\n- **Initiative 1** (Owner: growth) <x> & more",
            "inbox_url": "https://x/c/1?a=1&b=2",
        }
    )
    assert "<x>" not in out and "&lt;x&gt;" in out
    assert "A &amp; B &lt;Co&gt;" in out
    assert "&amp; more" in out
    assert "**Initiative 1**" in out
    assert "<b>Needs your approval</b>" in out
    assert '<a href="https://x/c/1?a=1&amp;b=2">Open the decision inbox</a>' in out


@requires_db
async def test_telegram_webhook_links_chat_from_start_token(session_factory, company_with_budget, monkeypatch):
    import app.api.webhooks_telegram as tg_api
    from app.security import create_telegram_connect_token

    sent: list = []

    async def _fake_send(chat_id, text):
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(tg_api.telegram_svc, "send_message", _fake_send)
    monkeypatch.setattr(tg_api.settings, "telegram_webhook_secret", "")

    company_id = company_with_budget
    token = create_telegram_connect_token(company_id)

    class _Req:
        headers: dict = {}

        async def json(self):
            return {"message": {"chat": {"id": 999}, "text": f"/start {token}"}}

    async with session_factory() as db:
        result = await tg_api.telegram_update(_Req(), db)
    assert result == {"ok": True}
    async with session_factory() as db:
        cfg = await dlg.get_config(db, company_id)
    assert cfg.telegram_chat_id == "999"
    assert any("Connected" in t for _, t in sent)


@requires_db
async def test_telegram_reply_resolves_decision_and_acks(
    session_factory, company_with_budget, monkeypatch
):
    import app.api.webhooks_telegram as tg_api
    from app.services import decisions as decisions_svc

    sent: list = []
    reactions: list = []
    enqueued: list = []

    async def _fake_send(chat_id, text):
        sent.append((chat_id, text))
        return True

    async def _fake_react(chat_id, message_id, emoji="👍"):
        reactions.append((chat_id, message_id, emoji))
        return True

    async def _fake_enqueue(task_id, **kw):
        enqueued.append(task_id)

    async def _noop_write(*a, **k):
        return None

    monkeypatch.setattr(tg_api.telegram_svc, "send_message", _fake_send)
    monkeypatch.setattr(tg_api.telegram_svc, "set_reaction", _fake_react)
    monkeypatch.setattr(tg_api, "enqueue_task", _fake_enqueue)
    monkeypatch.setattr(tg_api.settings, "telegram_webhook_secret", "")
    monkeypatch.setattr(decisions_svc.memory_svc, "write", _noop_write)

    company_id = company_with_budget
    async with session_factory() as db:
        await dlg.link_telegram(db, company_id=company_id, chat_id="555")
        await db.commit()
    task_id, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.plan_approval, payload={}
    )

    class _Req:
        headers: dict = {}

        async def json(self):
            return {"message": {"chat": {"id": 555}, "message_id": 42, "text": "Approved"}}

    async with session_factory() as db:
        result = await tg_api.telegram_update(_Req(), db)
    assert result == {"ok": True}

    async with session_factory() as db:
        d = await db.get(DecisionRequest, decision_id)
        assert d.status is DecisionStatus.approved
    assert enqueued == [task_id]
    assert reactions == [("555", 42, "👍")]


@requires_db
async def test_telegram_reply_from_unlinked_chat_is_guided(
    session_factory, company_with_budget, monkeypatch
):
    import app.api.webhooks_telegram as tg_api

    sent: list = []

    async def _fake_send(chat_id, text):
        sent.append((chat_id, text))
        return True

    monkeypatch.setattr(tg_api.telegram_svc, "send_message", _fake_send)
    monkeypatch.setattr(tg_api.settings, "telegram_webhook_secret", "")

    class _Req:
        headers: dict = {}

        async def json(self):
            return {"message": {"chat": {"id": 777}, "message_id": 1, "text": "yes"}}

    async with session_factory() as db:
        result = await tg_api.telegram_update(_Req(), db)
    assert result == {"ok": True}
    assert any("Connect Telegram" in t for _, t in sent)
