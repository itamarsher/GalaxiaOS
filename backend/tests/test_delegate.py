"""Founder decision delegate: autonomy-level gating, config + signed webhooks,
auto-resolve / escalation, and the handled-once marker."""

from __future__ import annotations

from app.models import Agent, AgentRun, Company, DecisionRequest, Policy, Task
from app.models.enums import (
    AgentRole,
    DecisionKind,
    DecisionStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.services import chat
from app.services import delegate as dlg
from tests.conftest import requires_db


def _cfg(level, webhooks=(), secret=None):
    return dlg.DelegateConfig(
        autonomy_level=level,
        webhooks=tuple(dlg.WebhookTarget(u, e) for u, e in webhooks),
        signing_secret=secret,
    )


def _dec(kind, payload=None):
    return DecisionRequest(kind=kind, payload=payload or {}, summary="x")


def test_level_policy_maps_the_slider():
    assert dlg.level_policy(1).enabled is False
    assert dlg.level_policy(2).auto_kinds == dlg._LOW_STAKES
    assert dlg.level_policy(3).spend_cap_cents == 5000
    assert dlg.level_policy(4).spend_cap_cents is None  # within-budget
    assert DecisionKind.external_comm.value in dlg.level_policy(4).auto_kinds


def test_eligibility_is_the_hard_gate_per_level():
    # L1 manual: nothing auto.
    assert dlg._auto_eligible(_cfg(1), _dec(DecisionKind.plan_approval)) is False
    # L2 assisted: plans + low-stakes yes, spend never, hires/external no.
    assert dlg._auto_eligible(_cfg(2), _dec(DecisionKind.plan_approval)) is True
    assert dlg._auto_eligible(_cfg(2), _dec(DecisionKind.user_action)) is True
    assert dlg._auto_eligible(_cfg(2), _dec(DecisionKind.spend_approval, {"amount_cents": 1})) is False
    assert dlg._auto_eligible(_cfg(2), _dec(DecisionKind.hire_approval)) is False
    # L3 supervised: spend up to the $50 cap.
    assert dlg._auto_eligible(_cfg(3), _dec(DecisionKind.spend_approval, {"amount_cents": 5000})) is True
    assert dlg._auto_eligible(_cfg(3), _dec(DecisionKind.spend_approval, {"amount_cents": 5001})) is False
    assert dlg._auto_eligible(_cfg(3), _dec(DecisionKind.external_comm)) is False
    # L4 autonomous: hires + external eligible; spend escalates only when extreme.
    assert dlg._auto_eligible(_cfg(4), _dec(DecisionKind.external_comm)) is True
    assert dlg._auto_eligible(_cfg(4), _dec(DecisionKind.hire_approval)) is True
    big_budget = 1_000_000  # $10k remaining → extreme floor = max($1000, 50%) = $5000
    assert dlg._auto_eligible(_cfg(4), _dec(DecisionKind.spend_approval, {"amount_cents": 400000}), big_budget) is True
    assert dlg._auto_eligible(_cfg(4), _dec(DecisionKind.spend_approval, {"amount_cents": 600000}), big_budget) is False


def test_webhook_wants_filters_by_disposition():
    assert dlg.webhook_wants("all", "escalated") is True
    assert dlg.webhook_wants("all", "auto_approved") is True
    assert dlg.webhook_wants("escalations", "escalated") is True
    assert dlg.webhook_wants("escalations", "auto_approved") is False
    assert dlg.webhook_wants("auto_handled", "auto_rejected") is True
    assert dlg.webhook_wants("auto_handled", "escalated") is False


def test_sign_payload_is_stable_hmac():
    sig = dlg.sign_payload("shhh", "1700000000", '{"a":1}')
    assert sig.startswith("sha256=")
    # Deterministic for the same inputs; changes with the body.
    assert sig == dlg.sign_payload("shhh", "1700000000", '{"a":1}')
    assert sig != dlg.sign_payload("shhh", "1700000000", '{"a":2}')


async def test_send_webhook_is_best_effort():
    assert await dlg.send_webhook("http://127.0.0.1:9/nope", {"x": 1}, secret="s") is False


@requires_db
async def test_set_config_mints_and_rotates_secret(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        # A webhook auto-mints a signing secret (spoof protection on by default).
        cfg = await dlg.set_config(
            db,
            company_id=company_id,
            autonomy_level=3,
            webhooks=[{"url": "https://hooks.example.com/a", "events": "escalations"},
                      {"url": "https://hooks.example.com/b", "events": "bogus"}],  # events dropped→"all"? no: filtered
            rotate_secret=False,
        )
        await db.commit()
    assert cfg.autonomy_level == 3
    # The bogus-events entry is filtered out; the valid one survives.
    assert len(cfg.webhooks) == 1 and cfg.webhooks[0].events == "escalations"
    first_secret = cfg.signing_secret
    assert first_secret and len(first_secret) >= 32

    async with session_factory() as db:
        again = await dlg.get_config(db, company_id)
    assert again.signing_secret == first_secret  # stable across reads

    async with session_factory() as db:
        rotated = await dlg.set_config(
            db, company_id=company_id, autonomy_level=4,
            webhooks=[{"url": "https://hooks.example.com/a", "events": "all"}],
            rotate_secret=True,
        )
        await db.commit()
    assert rotated.signing_secret != first_secret
    assert rotated.autonomy_level == 4


@requires_db
async def test_parse_migrates_legacy_config(session_factory, company_with_budget):
    """An old pre-slider row (auto_pilot + single webhook_url) reads as level 2 with
    the URL migrated into the webhook list."""
    company_id = company_with_budget
    async with session_factory() as db:
        from app.models.enums import PolicyEffect, PolicyScope

        db.add(
            Policy(
                company_id=company_id,
                name=dlg.DELEGATE_POLICY_NAME,
                scope=PolicyScope.global_,
                rule={
                    "auto_pilot_enabled": True,
                    "auto_kinds": ["plan_approval"],
                    "webhook_url": "https://old.example.com/hook",
                },
                effect=PolicyEffect.allow,
                priority=1000,
            )
        )
        await db.commit()
    async with session_factory() as db:
        cfg = await dlg.get_config(db, company_id)
    assert cfg.autonomy_level == 2
    assert [w.url for w in cfg.webhooks] == ["https://old.example.com/hook"]


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
async def test_handle_auto_approves_at_assisted_level(session_factory, company_with_budget, monkeypatch):
    company_id = company_with_budget

    async def _approve(db, *, company_id, decision):
        return "approve", "Routine on-mission plan."

    monkeypatch.setattr(dlg, "_triage", _approve)
    monkeypatch.setattr(dlg.settings, "public_api_base_url", "https://api.test")
    from app.services import decisions as decisions_svc

    async def _noop_write(*a, **k):
        return None

    monkeypatch.setattr(decisions_svc.memory_svc, "write", _noop_write)

    task_id, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.plan_approval, payload={"tool": "submit_plan"}
    )
    cfg = _cfg(2, [("https://hooks.example.com/x", "all")], secret="sek")
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
async def test_handle_escalates_spend_below_supervised(session_factory, company_with_budget, monkeypatch):
    """At level 2 a spend decision is never eligible — the model is never consulted,
    it escalates, stays pending, and the webhook flags needs_you."""
    company_id = company_with_budget

    async def _boom(*a, **k):
        raise AssertionError("model must not be consulted for an ineligible decision")

    monkeypatch.setattr(dlg, "_triage", _boom)

    _t, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.spend_approval,
        payload={"tool": "register_domain", "amount_cents": 1200},
    )
    cfg = _cfg(2, [("https://hooks.example.com/x", "all")], secret="sek")
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
        assert d.payload.get("delegate", {}).get("disposition") == "escalated"


@requires_db
async def test_supervised_auto_approves_minor_spend_only(session_factory, company_with_budget, monkeypatch):
    """Level 3: spend at/under the cap triages (auto-approve); over the cap escalates."""
    company_id = company_with_budget

    async def _approve(db, *, company_id, decision):
        return "approve", "small, in-budget"

    monkeypatch.setattr(dlg, "_triage", _approve)
    from app.services import decisions as decisions_svc

    async def _noop_write(*a, **k):
        return None

    monkeypatch.setattr(decisions_svc.memory_svc, "write", _noop_write)
    cfg = _cfg(3)

    # Minor spend ($40 ≤ $50 cap) → auto-approved.
    _t, minor_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.spend_approval, payload={"amount_cents": 4000}
    )
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        outcome = await dlg.handle(db, company=company, decision=await db.get(DecisionRequest, minor_id), cfg=cfg)
        await db.commit()
    assert outcome.disposition == "auto_approved"

    # Larger spend ($60 > $50 cap) → escalated (model never consulted).
    _t2, big_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.spend_approval, payload={"amount_cents": 6000}
    )
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        outcome2 = await dlg.handle(db, company=company, decision=await db.get(DecisionRequest, big_id), cfg=cfg)
        await db.commit()
    assert outcome2.disposition == "escalated"


@requires_db
async def test_autonomous_escalates_only_extreme_spend(session_factory, company_with_budget, monkeypatch):
    """Level 4: ordinary spend auto-resolves; an extreme spend still escalates."""
    company_id = company_with_budget

    async def _approve(db, *, company_id, decision):
        return "approve", "within budget"

    monkeypatch.setattr(dlg, "_triage", _approve)
    from app.services import decisions as decisions_svc

    async def _noop_write(*a, **k):
        return None

    monkeypatch.setattr(decisions_svc.memory_svc, "write", _noop_write)
    cfg = _cfg(4)

    # $50 spend, remaining $10k → below the $1000 extreme floor → auto-approved.
    _t, ok_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.spend_approval, payload={"amount_cents": 5000}
    )
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        outcome = await dlg.handle(
            db, company=company, decision=await db.get(DecisionRequest, ok_id), cfg=cfg,
            remaining_budget_cents=1_000_000,
        )
        await db.commit()
    assert outcome.disposition == "auto_approved"

    # $6000 spend → over the extreme floor (50% of $10k = $5000) → escalates.
    _t2, extreme_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.spend_approval, payload={"amount_cents": 600000}
    )
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        outcome2 = await dlg.handle(
            db, company=company, decision=await db.get(DecisionRequest, extreme_id), cfg=cfg,
            remaining_budget_cents=1_000_000,
        )
        await db.commit()
    assert outcome2.disposition == "escalated"


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
