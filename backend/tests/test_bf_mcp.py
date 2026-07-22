"""Tests for the Business-Function MCP endpoint (RFC 0001, pull transport).

Covers the connection-token mint/verify, and drives the MCP server end-to-end via
TestClient — initialize, tools/list, and the tools/call lifecycle (get_mandate →
get_next_initiative → claim_initiative → report_result) — plus auth rejection.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.config import settings
from app.db import get_db
from app.models import (
    Agent,
    AgentRun,
    Budget,
    Company,
    Membership,
    MetricSignal,
    Mission,
    Task,
    User,
)
from app.models.enums import (
    AgentRole,
    BudgetPeriod,
    CompanyStatus,
    MembershipRole,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.security import create_access_token
from app.services import function_token
from tests.conftest import requires_db

_SECRET = "test-connection-secret"


# ── token round-trip (no DB) ───────────────────────────────────────────────────
def test_mint_and_verify_round_trip(monkeypatch):
    monkeypatch.setattr(settings, "function_connection_secret", _SECRET)
    company_id, agent_id = uuid.uuid4(), uuid.uuid4()
    token = function_token.mint(company_id=company_id, agent_id=agent_id)
    assert function_token.verify(token) == (company_id, agent_id)


def test_verify_rejects_tampered_and_disabled(monkeypatch):
    monkeypatch.setattr(settings, "function_connection_secret", _SECRET)
    token = function_token.mint(company_id=uuid.uuid4(), agent_id=uuid.uuid4())
    # Tamper the FIRST signature char — a fully-significant base64 position, so the
    # decoded signature always changes. (Tampering the last char is flaky: base64's
    # final char carries unused bits, so a tail edit can decode to the same bytes.)
    p_b64, _, s_b64 = token.partition(".")
    flipped = ("B" if s_b64[0] != "B" else "C") + s_b64[1:]
    assert function_token.verify(f"{p_b64}.{flipped}") is None  # bad signature
    assert function_token.verify("garbage") is None
    # With no secret configured the transport is disabled — mint raises, verify fails.
    monkeypatch.setattr(settings, "function_connection_secret", "")
    assert function_token.verify(token) is None
    with pytest.raises(function_token.TokensDisabled):
        function_token.mint(company_id=uuid.uuid4(), agent_id=uuid.uuid4())


# ── shared setup ───────────────────────────────────────────────────────────────
@dataclass
class _Ids:
    user_id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID
    task_id: uuid.UUID


async def _seed(session_factory) -> _Ids:
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Membership(user_id=user.id, company_id=company.id, role=MembershipRole.founder))
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=10_000))
        db.add(Mission(company_id=company.id, raw_text="Grow the thing.", constraints=["No ads"]))
        agent = Agent(company_id=company.id, role=AgentRole.growth, name="Growth Lead",
                      monthly_budget_cents=5_000)
        db.add(agent)
        await db.flush()
        run = AgentRun(company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(company_id=company.id, run_id=run.id, root_run_id=run.id, agent_id=agent.id,
                    goal="publish the launch page", status=TaskStatus.queued)
        db.add(task)
        await db.commit()
        return _Ids(user.id, company.id, agent.id, task.id)


def _client() -> TestClient:
    async def _override_db():
        engine = create_async_engine(os.environ["ABOS_TEST_DATABASE_URL"], future=True)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                yield db
        finally:
            await engine.dispose()

    app = main.create_app()
    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _rpc(client, token, method, params=None, mid=1):
    return client.post(
        "/connect/business-function",
        headers={"Authorization": f"Bearer {token}"},
        json={"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}},
    )


def _tool(client, token, name, arguments=None):
    r = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments or {}})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    return json.loads(result["content"][0]["text"]), result


# ── the MCP server, end to end ─────────────────────────────────────────────────
@requires_db
async def test_mcp_endpoint_full_lifecycle(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "function_connection_secret", _SECRET)
    ids = await _seed(session_factory)
    token = function_token.mint(company_id=ids.company_id, agent_id=ids.agent_id)

    with _client() as client:
        # Handshake.
        r = _rpc(client, token, "initialize")
        assert r.status_code == 200 and r.json()["result"]["protocolVersion"]
        assert _rpc(client, token, "notifications/initialized").status_code == 202

        # Discovery.
        tools = {t["name"] for t in _rpc(client, token, "tools/list").json()["result"]["tools"]}
        assert {"get_mandate", "get_next_initiative", "claim_initiative", "report_result",
                "record_metric", "write_memory", "request_budget",
                "get_business_state", "post_update", "request_decision"} <= tools

        # A within-budget spend clears synchronously (the $100 monthly budget covers $10).
        cleared, _ = _tool(client, token, "request_budget", {"amount_cents": 1000, "reason": "a tool"})
        assert cleared["cleared"] is True

        # Mandate is scoped to this function.
        mandate, _ = _tool(client, token, "get_mandate")
        assert mandate["function"] == "growth" and "No ads" in mandate["constraints"]

        # The offered initiative, then claim it.
        nxt, _ = _tool(client, token, "get_next_initiative")
        assert nxt["initiative"]["goal"] == "publish the launch page"
        claimed, _ = _tool(client, token, "claim_initiative", {"initiative_id": str(ids.task_id)})
        assert claimed["claimed"] is True

        # A worker can record a real metric back over the surface.
        rec, _ = _tool(client, token, "record_metric",
                       {"name": "signups", "value": 12, "unit": "users", "note": "launch day"})
        assert rec["ok"] is True and rec["metric_id"]

        # It can read a full business-state snapshot: it just claimed one initiative.
        state, _ = _tool(client, token, "get_business_state")
        assert state["function"] == "growth" and state["company_name"] == "T"
        assert state["initiatives_running"] == 1

        # It can escalate a non-budget decision to the founder (governance stays here).
        dec, _ = _tool(client, token, "request_decision",
                       {"summary": "Pause the paid channel?", "kind": "strategy"})
        assert dec["escalated"] is True and dec["kind"] == "strategy" and dec["decision_id"]

        # Report it done.
        done, _ = _tool(client, token, "report_result",
                        {"initiative_id": str(ids.task_id), "outcome": "done", "summary": "live"})
        assert done["ok"] is True

    async with session_factory() as db:
        assert (await db.get(Task, ids.task_id)).status is TaskStatus.done
        sig = (await db.scalars(select(MetricSignal).where(MetricSignal.name == "signups"))).one()
        assert sig.value == 12 and sig.source.value == "agent"


@requires_db
async def test_report_bug_and_monitor_via_mcp(session_factory, monkeypatch):
    """A connected operator can file a bug into the backlog and monitor its status
    over the MCP surface (report_bug + list_feature_requests)."""
    monkeypatch.setattr(settings, "function_connection_secret", _SECRET)
    ids = await _seed(session_factory)
    token = function_token.mint(company_id=ids.company_id, agent_id=ids.agent_id)

    with _client() as client:
        tools = {t["name"] for t in _rpc(client, token, "tools/list").json()["result"]["tools"]}
        assert {"report_bug", "list_feature_requests"} <= tools

        filed, _ = _tool(client, token, "report_bug", {
            "title": "Company name is set to the mission sentence",
            "details": "Onboarding names the company with the full tagline instead of a short name.",
        })
        assert filed["ok"] is True
        assert filed["status"] == "open"
        assert filed["new_entry"] is True
        fr_id = filed["feature_request_id"]

        listing, _ = _tool(client, token, "list_feature_requests")
        assert listing["count"] == 1
        entry = listing["requests"][0]
        assert entry["id"] == fr_id
        assert entry["kind"] == "bug"
        assert entry["status"] == "open"
        assert entry["issue_url"] is None

    # The bug is a real backlog row attributed to this company.
    from app.models import FeatureRequest
    async with session_factory() as db:
        fr = await db.get(FeatureRequest, uuid.UUID(fr_id))
        assert fr is not None and fr.kind.value == "bug"


@requires_db
async def test_operator_bug_lifecycle_via_mcp_matches_native_gate(session_factory, monkeypatch):
    """The operator-only bug tools (review_backlog / promote / deliver) are exposed on
    MCP with the SAME operator gate the native agent tools use — so the lifecycle is
    agnostic to whether an internal or an MCP agent drives it."""
    monkeypatch.setattr(settings, "function_connection_secret", _SECRET)
    ids = await _seed(session_factory)
    token = function_token.mint(company_id=ids.company_id, agent_id=ids.agent_id)

    with _client() as client:
        # File a bug (any company can report).
        filed, _ = _tool(client, token, "report_bug",
                         {"title": "Cross-cycle race", "details": "next cycle clobbers a claimed task"})
        fr_id = filed["feature_request_id"]

        # NOT the operator company → operator tools are refused (plain-text error result).
        monkeypatch.setattr(settings, "platform_company_id", "")
        res = _rpc(client, token, "tools/call", {"name": "review_backlog", "arguments": {}}).json()["result"]
        assert res.get("isError") is True and "operator company only" in res["content"][0]["text"]
        res = _rpc(client, token, "tools/call",
                   {"name": "deliver_feature_request", "arguments": {"feature_request_id": fr_id}}).json()["result"]
        assert res.get("isError") is True

        # Designate THIS company as the operator → identical tools now authorized.
        monkeypatch.setattr(settings, "platform_company_id", str(ids.company_id))
        backlog, _ = _tool(client, token, "review_backlog", {})
        assert backlog["count"] >= 1
        assert any(e["id"] == fr_id for e in backlog["backlog"])

        # promote runs past the gate; with no GitHub tracker configured it reports the
        # missing-tracker path (same as the native promoter) rather than being denied.
        res = _rpc(client, token, "tools/call",
                   {"name": "promote_feature_request", "arguments": {"feature_request_id": fr_id}}
                   ).json()["result"]
        assert res.get("isError") is True and "tracker" in res["content"][0]["text"].lower()

    # Still open (promotion couldn't file without a tracker) — the entry is intact.
    from app.models import FeatureRequest
    async with session_factory() as db:
        fr = await db.get(FeatureRequest, uuid.UUID(fr_id))
        assert fr.status.value == "open"


@requires_db
async def test_mcp_endpoint_rejects_bad_or_missing_token(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "function_connection_secret", _SECRET)
    with _client() as client:
        assert client.post(
            "/connect/business-function",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        ).status_code == 401
        assert _rpc(client, "not-a-real-token", "tools/list").status_code == 401


@requires_db
async def test_mint_endpoint_issues_a_working_token(session_factory, monkeypatch):
    monkeypatch.setattr(settings, "function_connection_secret", _SECRET)
    ids = await _seed(session_factory)
    jwt = create_access_token(ids.user_id)

    with _client() as client:
        r = client.post(
            f"/companies/{ids.company_id}/functions/{ids.agent_id}/connection",
            headers={"Authorization": f"Bearer {jwt}"},
        )
        assert r.status_code == 200, r.text
        token = r.json()["token"]
    assert function_token.verify(token) == (ids.company_id, ids.agent_id)
