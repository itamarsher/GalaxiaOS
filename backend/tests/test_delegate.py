"""Founder decision delegate: config, the hard eligibility gate, auto-resolve, and
escalation-with-webhook."""

from __future__ import annotations

from app.models import Agent, AgentRun, Company, DecisionRequest, Task
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


def test_auto_eligible_is_the_hard_gate():
    """Eligibility is decided in code before any model call: kind must be allowed,
    external comms are never eligible, and spend must sit under the cap."""
    cfg = dlg.DelegateConfig(
        webhook_url=None,
        auto_pilot_enabled=True,
        auto_kinds=("plan_approval", "user_action", "spend_approval"),
        max_auto_spend_cents=0,
    )

    def dec(kind, payload=None):
        return DecisionRequest(kind=kind, payload=payload or {}, summary="x")

    assert dlg._auto_eligible(cfg, dec(DecisionKind.plan_approval)) is True
    assert dlg._auto_eligible(cfg, dec(DecisionKind.user_action)) is True
    # Not in the allow-list -> escalate.
    assert dlg._auto_eligible(cfg, dec(DecisionKind.hire_approval)) is False
    # Spend must be within the (here: zero) cap.
    assert dlg._auto_eligible(cfg, dec(DecisionKind.spend_approval, {"amount_cents": 50})) is False
    assert dlg._auto_eligible(cfg, dec(DecisionKind.spend_approval, {"amount_cents": 0})) is True
    # External comms are never eligible, even if somehow listed.
    ext_cfg = dlg.DelegateConfig(None, True, ("external_comm",), 100000)
    assert dlg._auto_eligible(ext_cfg, dec(DecisionKind.external_comm)) is False


@requires_db
async def test_set_config_filters_forbidden_kinds(session_factory, company_with_budget):
    company_id = company_with_budget
    async with session_factory() as db:
        cfg = await dlg.set_config(
            db,
            company_id=company_id,
            webhook_url="https://hooks.example.com/abc",
            auto_pilot_enabled=True,
            auto_kinds=["plan_approval", "external_comm", "nonsense"],
            max_auto_spend_cents=0,
        )
        await db.commit()
    # external_comm / unknown are dropped; only the allowed kind survives.
    assert cfg.auto_kinds == ("plan_approval",)
    assert cfg.webhook_url == "https://hooks.example.com/abc"
    async with session_factory() as db:
        reread = await dlg.get_config(db, company_id)
    assert reread.auto_pilot_enabled is True
    assert reread.auto_kinds == ("plan_approval",)


async def _pending_decision(session_factory, company_id, *, kind, payload):
    """A pending decision surfaced in the agent↔founder DM, task in waiting_approval."""
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add(agent)
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id, run_id=run.id, root_run_id=run.id,
            agent_id=agent.id, goal="g", status=TaskStatus.waiting_approval,
        )
        db.add(task)
        await db.flush()
        decision = DecisionRequest(
            company_id=company_id, agent_id=agent.id, task_id=task.id,
            kind=kind, summary="Proposed plan: ship the docs", payload=payload,
            status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.flush()
        await chat.attach_decision_dm(db, decision=decision)
        await db.commit()
        return task.id, decision.id


@requires_db
async def test_handle_auto_approves_routine_decision(
    session_factory, company_with_budget, monkeypatch
):
    """With auto-pilot on and the model saying approve, a plan decision resolves
    through the normal path (task resumed) and is stamped handled, with an FYI
    webhook payload."""
    company_id = company_with_budget

    async def _approve(db, *, company_id, decision):
        return "approve", "Routine on-mission plan."

    monkeypatch.setattr(dlg, "_triage", _approve)
    # Founder note -> memory_entries, which the test schema omits; stub the write.
    from app.services import decisions as decisions_svc

    async def _noop_write(*a, **k):
        return None

    monkeypatch.setattr(decisions_svc.memory_svc, "write", _noop_write)

    task_id, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.plan_approval, payload={"tool": "submit_plan"}
    )
    cfg = dlg.DelegateConfig(
        webhook_url="https://hooks.example.com/x",
        auto_pilot_enabled=True,
        auto_kinds=("plan_approval",),
        max_auto_spend_cents=0,
    )
    async with session_factory() as db:
        company = await db.get(Company, company_id)
        decision = await db.get(DecisionRequest, decision_id)
        outcome = await dlg.handle(db, company=company, decision=decision, cfg=cfg)
        await db.commit()

    assert outcome.disposition == "auto_approved"
    assert outcome.resumed_task_id == task_id
    assert outcome.webhook_payload["disposition"] == "auto_approved"
    assert outcome.webhook_payload["needs_you"] is False
    async with session_factory() as db:
        d = await db.get(DecisionRequest, decision_id)
        assert d.status is DecisionStatus.approved
        assert d.payload.get("delegate", {}).get("disposition") == "auto_approved"
        t = await db.get(Task, task_id)
        assert t.status is TaskStatus.queued  # resumed


@requires_db
async def test_handle_escalates_ineligible_decision(
    session_factory, company_with_budget, monkeypatch
):
    """A spend decision (not in the allow-list / over the $0 cap) is never sent to
    the model — it's escalated, stays pending, and the webhook flags needs_you."""
    company_id = company_with_budget

    async def _boom(*a, **k):
        raise AssertionError("the model must not be consulted for an ineligible decision")

    monkeypatch.setattr(dlg, "_triage", _boom)

    _task_id, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.spend_approval,
        payload={"tool": "register_domain", "amount_cents": 1200},
    )
    cfg = dlg.DelegateConfig(
        webhook_url="https://hooks.example.com/x",
        auto_pilot_enabled=True,
        auto_kinds=("plan_approval",),  # spend NOT allowed
        max_auto_spend_cents=0,
    )
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
        assert d.status is DecisionStatus.pending  # untouched, waits for the founder
        assert d.payload.get("delegate", {}).get("disposition") == "escalated"


@requires_db
async def test_untriaged_pending_excludes_already_handled(session_factory, company_with_budget):
    """Once stamped, a still-pending (escalated) decision isn't re-picked."""
    company_id = company_with_budget
    _t, decision_id = await _pending_decision(
        session_factory, company_id, kind=DecisionKind.plan_approval, payload={}
    )
    async with session_factory() as db:
        before = await dlg.untriaged_pending(db, company_id)
        assert any(d.id == decision_id for d in before)
        d = await db.get(DecisionRequest, decision_id)
        d.payload = {**(d.payload or {}), "delegate": {"disposition": "escalated"}}
        await db.commit()
    async with session_factory() as db:
        after = await dlg.untriaged_pending(db, company_id)
        assert all(d.id != decision_id for d in after)


async def test_send_webhook_is_best_effort():
    """A dead/invalid webhook returns False instead of raising."""
    ok = await dlg.send_webhook("http://127.0.0.1:9/definitely-not-listening", {"x": 1})
    assert ok is False
