"""Generic encrypted secrets: store/list/revoke, the placeholder broker, redaction,
and the request→fulfil decision flow (the value never leaks to memory/DM/payload).

DB-backed (real ``secrets`` rows + RLS). Skipped unless ``ABOS_TEST_DATABASE_URL``
is set.
"""

from __future__ import annotations

import base64
import os
import uuid

from sqlalchemy import func, select

from app.config import settings
from app.models import (
    Agent,
    AgentRun,
    ChatMessage,
    Company,
    DecisionRequest,
    Secret,
    Task,
    User,
)
from app.models.enums import (
    AgentRole,
    CompanyStatus,
    DecisionKind,
    DecisionStatus,
    RunStatus,
    RunTrigger,
    SecretStatus,
    TaskStatus,
)
from app.runtime.tools import execute_tool
from app.services import secrets as secrets_svc
from tests.conftest import requires_db

pytestmark = requires_db

_VALUE = "sk-live-SUPERSECRETvalue-9999"


def _set_master_key() -> None:
    if not settings.master_key:
        settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


async def _company(db) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
    db.add(user)
    await db.flush()
    company = Company(owner_user_id=user.id, name="C", status=CompanyStatus.active)
    db.add(company)
    await db.flush()
    return company.id


async def _agent_and_task(db, company_id: uuid.UUID) -> tuple[Agent, Task]:
    agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
    db.add(agent)
    await db.flush()
    run = AgentRun(company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running)
    db.add(run)
    await db.flush()
    run.root_run_id = run.id
    task = Task(
        company_id=company_id,
        run_id=run.id,
        root_run_id=run.id,
        agent_id=agent.id,
        goal="do the thing",
        status=TaskStatus.running,
    )
    db.add(task)
    await db.flush()
    return agent, task


# ── storage + fingerprint ─────────────────────────────────────────────────────


@requires_db
async def test_store_seals_and_exposes_fingerprint_only(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        row = await secrets_svc.store_secret(
            db, company_id=cid, name="Stripe API Key", plaintext=_VALUE
        )
        await db.commit()
        # Name is normalised; the ciphertext is not the plaintext; fingerprint is safe.
        assert row.name == "stripe_api_key"
        assert _VALUE.encode() not in row.encrypted_value
        assert row.fingerprint == "sk-…9999"
        assert _VALUE not in row.fingerprint

    # Listing never decrypts; a re-store revokes the old one (single active per name).
    async with session_factory() as db:
        listed = await secrets_svc.list_secrets(db, company_id=cid)
        assert [s.name for s in listed] == ["stripe_api_key"]
        await secrets_svc.store_secret(db, company_id=cid, name="stripe_api_key", plaintext="new")
        await db.commit()
        active = await db.scalar(
            select(func.count()).select_from(Secret).where(
                Secret.company_id == cid, Secret.status == SecretStatus.active
            )
        )
        assert active == 1


@requires_db
async def test_revoke(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        row = await secrets_svc.store_secret(db, company_id=cid, name="k", plaintext="v")
        await db.commit()
        sid = row.id
    async with session_factory() as db:
        assert await secrets_svc.revoke_secret(db, company_id=cid, secret_id=sid) is True
        await db.commit()
    async with session_factory() as db:
        assert await secrets_svc.has_secret(db, company_id=cid, name="k") is False
        # Revoking again is a no-op / False.
        assert await secrets_svc.revoke_secret(db, company_id=cid, secret_id=sid) is False


# ── the broker: substitute at the boundary, on a copy ─────────────────────────


@requires_db
async def test_broker_substitutes_into_a_copy(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        await secrets_svc.store_secret(db, company_id=cid, name="api_key", plaintext=_VALUE)
        await db.commit()

    args = {"headers": {"Authorization": "Bearer {{secret:api_key}}"}, "url": "https://x.io"}
    async with session_factory() as db:
        out, used = await secrets_svc.resolve_placeholders(db, company_id=cid, args=args)
    assert used == {"api_key"}
    assert out["headers"]["Authorization"] == f"Bearer {_VALUE}"
    # The ORIGINAL args are untouched — the placeholder (not the value) is what the
    # caller persists to transcripts / decision payloads.
    assert args["headers"]["Authorization"] == "Bearer {{secret:api_key}}"


@requires_db
async def test_broker_leaves_unknown_placeholder_verbatim(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        await secrets_svc.store_secret(db, company_id=cid, name="known", plaintext="v")
        await db.commit()
    async with session_factory() as db:
        out, used = await secrets_svc.resolve_placeholders(
            db, company_id=cid, args={"a": "{{secret:missing}}"}
        )
    assert used == set()
    assert out["a"] == "{{secret:missing}}"


@requires_db
async def test_broker_host_binding(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        await secrets_svc.store_secret(
            db, company_id=cid, name="bound", plaintext=_VALUE, allowed_host="api.stripe.com"
        )
        await db.commit()

    # Wrong host → left as the placeholder (can't exfiltrate to another domain).
    async with session_factory() as db:
        out, used = await secrets_svc.resolve_placeholders(
            db, company_id=cid, args={"url": "https://evil.example/x?k={{secret:bound}}"}
        )
    assert used == set()
    assert "{{secret:bound}}" in out["url"]

    # Right host → substituted.
    async with session_factory() as db:
        out, used = await secrets_svc.resolve_placeholders(
            db,
            company_id=cid,
            args={"url": "https://api.stripe.com/v1?k={{secret:bound}}"},
        )
    assert used == {"bound"}
    assert _VALUE in out["url"]

    # Realistic shape: the secret is in a HEADER while the destination is a separate
    # ``url`` field. Host-binding must key off the call's url, not the header string.
    async with session_factory() as db:
        out, used = await secrets_svc.resolve_placeholders(
            db,
            company_id=cid,
            args={
                "url": "https://api.stripe.com/v1/charges",
                "headers": {"Authorization": "Bearer {{secret:bound}}"},
            },
        )
    assert used == {"bound"}
    assert out["headers"]["Authorization"] == f"Bearer {_VALUE}"

    # Same header, but the url points elsewhere → fail closed (placeholder kept).
    async with session_factory() as db:
        out, used = await secrets_svc.resolve_placeholders(
            db,
            company_id=cid,
            args={
                "url": "https://evil.example/collect",
                "headers": {"Authorization": "Bearer {{secret:bound}}"},
            },
        )
    assert used == set()
    assert out["headers"]["Authorization"] == "Bearer {{secret:bound}}"


# ── redaction (defence in depth) ──────────────────────────────────────────────


@requires_db
async def test_redact_text_masks_value(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        await secrets_svc.store_secret(db, company_id=cid, name="tok", plaintext=_VALUE)
        await db.commit()
    async with session_factory() as db:
        red = await secrets_svc.redact_text(
            db, company_id=cid, text=f"the token is {_VALUE} ok"
        )
    assert _VALUE not in red
    assert "[redacted secret: tok]" in red


@requires_db
async def test_redact_noop_without_secrets(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        await db.commit()
    async with session_factory() as db:
        text = "nothing to hide here"
        assert await secrets_svc.redact_text(db, company_id=cid, text=text) == text


# ── request_secret tool → parks + raises a value-free decision ────────────────


@requires_db
async def test_request_secret_tool_parks_and_raises_decision(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        agent, task = await _agent_and_task(db, cid)
        await db.commit()
        aid, tid = agent.id, task.id

    async with session_factory() as db:
        agent = await db.get(Agent, aid)
        task = await db.get(Task, tid)
        outcome = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="request_secret",
            args={"name": "Stripe API Key", "reason": "charge customers", "allowed_host": "api.stripe.com"},
        )
        await db.commit()
    assert outcome.park is True

    async with session_factory() as db:
        decision = await db.scalar(select(DecisionRequest).where(DecisionRequest.task_id == tid))
        row = await db.get(Task, tid)
    assert decision is not None
    assert decision.kind is DecisionKind.secret_request
    assert decision.payload["name"] == "stripe_api_key"
    assert decision.payload["allowed_host"] == "api.stripe.com"
    # The value is NOT in the request — only metadata.
    assert "value" not in decision.payload
    assert row.status is TaskStatus.waiting_approval


# ── fulfil → seals value, resumes task, NEVER leaks the value ─────────────────


@requires_db
async def test_fulfill_seals_value_resumes_task_and_never_leaks(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        agent, task = await _agent_and_task(db, cid)
        await db.flush()
        task.status = TaskStatus.waiting_approval
        decision = DecisionRequest(
            company_id=cid,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.secret_request,
            summary="Secret requested — `stripe_api_key`",
            payload={"tool": "request_secret", "name": "stripe_api_key", "reason": "charge", "allowed_host": None},
            status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.flush()
        from app.services import chat as chat_svc

        await chat_svc.attach_decision_dm(db, decision=decision)
        await db.commit()
        did, tid = decision.id, task.id

    async with session_factory() as db:
        decision = await db.get(DecisionRequest, did)
        resumed = await secrets_svc.fulfill_request(
            db, decision=decision, plaintext=_VALUE, user_id=None
        )
        await db.commit()
    assert resumed == tid

    async with session_factory() as db:
        # 1. The secret is sealed + active and decrypts back through the broker.
        out, used = await secrets_svc.resolve_placeholders(
            db, company_id=cid, args={"h": "{{secret:stripe_api_key}}"}
        )
        assert out["h"] == _VALUE and used == {"stripe_api_key"}

        # 2. The decision is approved and its payload still holds NO value.
        decision = await db.get(DecisionRequest, did)
        assert decision.status is DecisionStatus.approved
        assert "value" not in (decision.payload or {})

        # 3. The task resumed (queued) with a value-free ack directive.
        task = await db.get(Task, tid)
        assert task.status is TaskStatus.queued
        assert _VALUE not in (task.input or {}).get("founder_ack", "")

        # 4. THE KEY GUARANTEE: the value is nowhere in the founder-facing chat thread
        # (the DM only acknowledges the secret by name). ``memory_entries`` is excluded
        # from the test schema (pgvector); the fulfil path never calls memory.write at
        # all — unlike resolve_decision's _apply_note — which is what keeps it out of
        # memory. The redact_text tests separately prove the memory sink would scrub.
        chat_rows = (await db.scalars(select(ChatMessage).where(ChatMessage.company_id == cid))).all()
        assert chat_rows  # the DM acknowledgement exists
        assert all(_VALUE not in (c.body or "") for c in chat_rows)


@requires_db
async def test_chat_reply_never_resolves_a_secret_request(session_factory):
    """A founder reply in chat must NOT resolve a secret_request (which would leak the
    value via the generic _apply_note memory write) — it stays pending, no secret is
    stored, and the founder is steered to the secure form."""
    _set_master_key()
    from app.services import chat as chat_svc
    from app.services import decisions as decisions_svc

    async with session_factory() as db:
        cid = await _company(db)
        agent, task = await _agent_and_task(db, cid)
        task.status = TaskStatus.waiting_approval
        decision = DecisionRequest(
            company_id=cid,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.secret_request,
            summary="Secret requested — `db_password`",
            payload={"tool": "request_secret", "name": "db_password", "reason": "connect"},
            status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.flush()
        channel = await chat_svc.attach_decision_dm(db, decision=decision)
        await db.commit()
        cid_, chan_id, did = cid, channel.id, decision.id

    async with session_factory() as db:
        resumed, verdict = await decisions_svc.try_resolve_from_reply(
            db, company_id=cid_, channel_id=chan_id, reply=_VALUE, user_id=None
        )
        await db.commit()
    assert (resumed, verdict) == (None, "unclear")

    async with session_factory() as db:
        # Still pending, and no secret was created from the chat reply.
        decision = await db.get(DecisionRequest, did)
        assert decision.status is DecisionStatus.pending
        count = await db.scalar(
            select(func.count()).select_from(Secret).where(Secret.company_id == cid_)
        )
        assert count == 0


@requires_db
async def test_fulfill_rejects_non_secret_decision(session_factory):
    _set_master_key()
    async with session_factory() as db:
        cid = await _company(db)
        agent, task = await _agent_and_task(db, cid)
        decision = DecisionRequest(
            company_id=cid,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.spend_approval,
            summary="not a secret",
            payload={},
            status=DecisionStatus.pending,
        )
        db.add(decision)
        await db.flush()
        raised = False
        try:
            await secrets_svc.fulfill_request(db, decision=decision, plaintext="v", user_id=None)
        except ValueError:
            raised = True
    assert raised is True
