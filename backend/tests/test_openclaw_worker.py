"""Tests for OpenClawWorker (RFC 0001, step 5 — push posture).

Fully offline: HTTP is exercised via httpx.MockTransport, so no live OpenClaw
Gateway is needed. Covers verdict parsing, the request Galaxia sends, config
gating, and an end-to-end ConnectedBackend + OpenClawWorker run.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.config import settings
from app.models import Agent, AgentRun, Budget, Company, Mission, Task, User
from app.models.enums import (
    AgentRole,
    BudgetPeriod,
    CompanyStatus,
    RunStatus,
    RunTrigger,
    TaskStatus,
)
from app.runtime.backends.connected import ConnectedBackend
from app.runtime.backends.openclaw_worker import OpenClawWorker, default_openclaw_worker
from app.services.business_function import BudgetEnvelope, Initiative, Mandate
from tests.conftest import requires_db


def _mandate(**over):
    base = dict(
        company_id=uuid.uuid4(), function="growth", function_title="Growth Lead",
        mission="Grow the thing.", language=None, objectives="1. Capture demand",
        metrics="", constraints=["No paid ads"],
        budget=BudgetEnvelope(function_remaining_cents=500),
    )
    base.update(over)
    return Mandate(**base)


def _initiative(goal="publish the launch page"):
    return Initiative(id=uuid.uuid4(), function="growth", goal=goal, status="running",
                      created_at="2026-07-01T00:00:00+00:00", budget=BudgetEnvelope())


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _completion(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


# ── verdict parsing ────────────────────────────────────────────────────────────
def test_parse_prefers_json_verdict():
    r = OpenClawWorker._parse(
        {"choices": [{"message": {"content": 'Done. {"outcome": "done", "summary": "page live"}'}}]}
    )
    assert r.outcome == "done" and r.output["summary"] == "page live"


def test_parse_maps_needs_decision():
    r = OpenClawWorker._parse(
        {"choices": [{"message": {"content": '{"outcome":"needs_decision","summary":"$500 ad test?"}'}}]}
    )
    assert r.outcome == "needs_decision" and "ad test" in r.output["summary"]


def test_parse_defaults_to_done_on_plain_text():
    # A reply with no JSON verdict means the agent did the work — never invent a fail.
    r = OpenClawWorker._parse({"choices": [{"message": {"content": "All finished, page is up."}}]})
    assert r.outcome == "done" and "page is up" in r.output["summary"]


def test_parse_handles_content_blocks_and_empty():
    r = OpenClawWorker._parse(
        {"choices": [{"message": {"content": [{"text": "hi"}, {"text": "there"}]}}]}
    )
    assert r.outcome == "done" and r.output["summary"] == "hi there"
    empty = OpenClawWorker._parse({})
    assert empty.outcome == "done" and empty.output["summary"] == "(no output)"


# ── the request Galaxia sends ──────────────────────────────────────────────────
async def test_execute_posts_briefing_and_routes_by_function():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _completion('{"outcome": "done", "summary": "ok"}')

    worker = OpenClawWorker(base_url="https://gw.test/", api_key="secret", client=_client(handler))
    mandate = _mandate()
    report = await worker.execute(mandate=mandate, initiative=_initiative())

    assert report.outcome == "done"
    assert seen["url"].endswith("/v1/chat/completions")
    assert seen["auth"] == "Bearer secret"
    # Routes to the per-tenant function persona (RFC 0001 §6): <company_id>:<function>.
    assert seen["body"]["model"] == f"openclaw/{mandate.company_id}:growth"
    assert "Growth Lead" in seen["body"]["messages"][0]["content"]  # mandate briefing
    assert "No paid ads" in seen["body"]["messages"][0]["content"]  # constraints
    assert "publish the launch page" in seen["body"]["messages"][1]["content"]  # initiative


async def test_execute_raises_on_http_error():
    worker = OpenClawWorker(
        base_url="https://gw.test", api_key="k",
        client=_client(lambda req: httpx.Response(500, text="boom")),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await worker.execute(mandate=_mandate(), initiative=_initiative())


# ── config gating ──────────────────────────────────────────────────────────────
def test_default_worker_none_without_base_url(monkeypatch):
    monkeypatch.setattr(settings, "openclaw_base_url", "")
    assert default_openclaw_worker() is None


def test_default_worker_built_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "openclaw_base_url", "https://gw.test")
    monkeypatch.setattr(settings, "openclaw_api_key", "k")
    monkeypatch.setattr(settings, "openclaw_model", "")
    assert isinstance(default_openclaw_worker(), OpenClawWorker)


# ── end-to-end: ConnectedBackend drives OpenClawWorker ─────────────────────────
@requires_db
async def test_connected_backend_with_openclaw_worker_finalizes(session_factory):
    async with session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@t.io", hashed_password="x")
        db.add(user)
        await db.flush()
        company = Company(owner_user_id=user.id, name="T", status=CompanyStatus.active)
        db.add(company)
        await db.flush()
        db.add(Budget(company_id=company.id, period=BudgetPeriod.monthly, limit_cents=10_000))
        db.add(Mission(company_id=company.id, raw_text="Grow.", constraints=[]))
        agent = Agent(company_id=company.id, role=AgentRole.growth, name="Growth Lead",
                      monthly_budget_cents=5_000)
        db.add(agent)
        await db.flush()
        run = AgentRun(company_id=company.id, trigger=RunTrigger.scheduled, status=RunStatus.running)
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(company_id=company.id, run_id=run.id, root_run_id=run.id, agent_id=agent.id,
                    goal="write the FAQ", status=TaskStatus.running,
                    created_at=datetime(2026, 7, 1, tzinfo=timezone.utc))
        db.add(task)
        await db.commit()
        task_id = task.id

    worker = OpenClawWorker(
        base_url="https://gw.test", api_key="k",
        client=_client(lambda req: _completion('Wrote it. {"outcome":"done","summary":"FAQ shipped"}')),
    )
    ctx = SimpleNamespace(session_factory=session_factory)
    result = await ConnectedBackend(worker=worker).run(ctx, agent, task)

    assert result["status"] == "done"
    async with session_factory() as db:
        row = await db.get(Task, task_id)
        assert row.status is TaskStatus.done and row.output.get("summary") == "FAQ shipped"
