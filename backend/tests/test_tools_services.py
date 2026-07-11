"""Agent self-service tool acquisition — `connect_service` and `configure_integration`.

`connect_service` registers an external MCP tool server; `configure_integration`
supplies credentials for a first-class BUILT-IN integration (Cloudflare) that
powers native capabilities (site hosting, custom domains, DNS). Both let an agent
wire up a capability without the founder. These tests cover the pure helpers
(DB-free) and the register/verify→store behaviour (DB-backed), including the
honest-failure and never-clobber guards.
"""

from __future__ import annotations

import base64
import os

from sqlalchemy import select

from app.models import Agent, AgentRun, McpServer, Task
from app.models.enums import AgentRole, MemoryType, RunStatus, RunTrigger
from app.runtime.tools import CORE_TOOL_NAMES, TOOL_SPECS, execute_tool
from app.runtime.tools import services as svc_tool
from app.services import integrations as integrations_svc
from app.services import mcp as mcp_svc
from tests.conftest import requires_db


def _set_master_key() -> None:
    """Give the envelope store a key so credential writes can encrypt."""
    from app.config import settings as app_settings

    app_settings.master_key = base64.urlsafe_b64encode(os.urandom(32)).decode()


class _FakeCtx:
    def __init__(self) -> None:
        self.enqueued: list = []

    async def enqueue_task(self, task_id):  # pragma: no cover - unused here
        self.enqueued.append(task_id)


class _FakeServer:
    def __init__(self, name: str, tools: list[dict]) -> None:
        self.name = name
        self.tools_cache = tools


def _fake_client(tools: list[dict] | None = None, *, error: str | None = None):
    class _Client:
        async def list_tools(self):
            if error is not None:
                raise mcp_svc.McpError(error)
            return tools or []

    return lambda server: _Client()


async def _make_task(session_factory, company_id):
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Growth")
        db.add(agent)
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.onboarding, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=agent.id,
            goal="grow",
        )
        db.add(task)
        await db.commit()
        return agent, task


# ── Pure / DB-free ──────────────────────────────────────────────────────────────
def test_connect_service_is_a_core_always_on_tool() -> None:
    # It must be always-on (like the other capability-acquisition primitives) so an
    # agent can reach for it without first discovering it.
    assert "connect_service" in CORE_TOOL_NAMES
    assert any(s.name == "connect_service" for s in TOOL_SPECS)


def test_url_validation_rejects_non_http() -> None:
    assert svc_tool._valid_url("https://mcp.acme.test/rpc") is True
    assert svc_tool._valid_url("http://localhost:9000") is True
    assert svc_tool._valid_url("not a url") is False
    assert svc_tool._valid_url("ftp://x.test") is False
    assert svc_tool._valid_url("") is False


def test_exposed_lists_namespaced_tool_names_and_truncates() -> None:
    server = _FakeServer("acme_crm", [{"name": f"t{i}"} for i in range(30)])
    exposed = svc_tool._exposed(server)
    assert "mcp__acme_crm__t0" in exposed
    assert "+5 more" in exposed  # 30 tools, 25 shown
    assert svc_tool._tool_names(server) == [f"t{i}" for i in range(30)]


# ── DB-backed: register → probe → expose ────────────────────────────────────────
@requires_db
async def test_connect_service_registers_and_exposes_tools(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)
    monkeypatch.setattr(
        mcp_svc,
        "_client",
        _fake_client([{"name": "create_issue", "description": "make an issue"}]),
    )
    # memory_entries is excluded from the test schema (pgvector); record the
    # audit-trail write instead of hitting the table.
    recorded: list[dict] = []

    async def _fake_write(db, **kwargs):
        recorded.append(kwargs)
        return None

    monkeypatch.setattr("app.services.memory.write", _fake_write)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="connect_service",
            args={"name": "Acme CRM", "url": "https://mcp.acme.test/rpc"},
        )
        await db.commit()

    assert outcome.is_error is False
    assert "mcp__acme_crm__create_issue" in outcome.observation
    # An audit trail is written so the founder can see the self-connected service.
    assert len(recorded) == 1
    assert recorded[0]["type"] is MemoryType.result
    assert "Acme CRM" in recorded[0]["title"]

    async with session_factory() as db:
        server = await db.scalar(select(McpServer).where(McpServer.company_id == company_id))
        # The service's tools are now resolvable for the whole company.
        specs, routing = await mcp_svc.tool_specs_for_company(db, company_id=company_id)
    assert server is not None and server.name == "acme_crm"
    assert any(s.name == "mcp__acme_crm__create_issue" for s in specs)
    assert "mcp__acme_crm__create_issue" in routing


@requires_db
async def test_failed_probe_rolls_back_a_new_registration(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)
    monkeypatch.setattr(mcp_svc, "_client", _fake_client(error="connection refused"))

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="connect_service",
            args={"name": "broken", "url": "https://nope.test"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "connection refused" in outcome.observation
    # A brand-new registration that couldn't be probed leaves no dead server behind.
    async with session_factory() as db:
        rows = (await db.scalars(select(McpServer).where(McpServer.company_id == company_id))).all()
    assert rows == []


@requires_db
async def test_empty_server_is_not_kept(session_factory, company_with_budget, monkeypatch):
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)
    monkeypatch.setattr(mcp_svc, "_client", _fake_client([]))  # reachable, but no tools

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="connect_service",
            args={"name": "empty", "url": "https://empty.test"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "no tools" in outcome.observation.lower()
    async with session_factory() as db:
        rows = (await db.scalars(select(McpServer).where(McpServer.company_id == company_id))).all()
    assert rows == []


@requires_db
async def test_connect_is_idempotent_and_does_not_clobber_a_working_server(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)

    # Seed a working server (as if the founder connected it) with a specific URL.
    async with session_factory() as db:
        server = await mcp_svc.add_server(
            db,
            company_id=company_id,
            name="Acme",
            label="Acme",
            url="https://original.test",
        )
        server.tools_cache = [{"name": "existing_tool"}]
        await db.commit()

    # A reconnect under the same name must NOT overwrite the good config or re-probe.
    def _boom(server):  # pragma: no cover - must never be called
        raise AssertionError("should not re-probe a healthy server")

    monkeypatch.setattr(mcp_svc, "_client", _boom)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="connect_service",
            args={"name": "Acme", "url": "https://malicious-overwrite.test"},
        )
        await db.commit()

    assert outcome.is_error is False
    assert "already connected" in outcome.observation.lower()
    async with session_factory() as db:
        row = await db.scalar(select(McpServer).where(McpServer.company_id == company_id))
    assert row.url == "https://original.test"  # untouched


@requires_db
async def test_connect_service_disabled_deployment(
    session_factory, company_with_budget, monkeypatch
):
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)
    monkeypatch.setattr(svc_tool.settings, "mcp_enabled", False)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="connect_service",
            args={"name": "acme", "url": "https://mcp.acme.test"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "disabled" in outcome.observation.lower()
    async with session_factory() as db:
        rows = (await db.scalars(select(McpServer).where(McpServer.company_id == company_id))).all()
    assert rows == []


@requires_db
async def test_invalid_url_does_nothing(session_factory, company_with_budget, monkeypatch):
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)
    # No client patch: a valid URL guard must reject before any network attempt.

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="connect_service",
            args={"name": "acme", "url": "not-a-url"},
        )
        await db.commit()

    assert outcome.is_error is True
    async with session_factory() as db:
        rows = (await db.scalars(select(McpServer).where(McpServer.company_id == company_id))).all()
    assert rows == []


# ── configure_integration (built-in Cloudflare adapter) ─────────────────────────
def test_configure_integration_is_a_core_always_on_tool() -> None:
    assert "configure_integration" in CORE_TOOL_NAMES
    assert any(s.name == "configure_integration" for s in TOOL_SPECS)


@requires_db
async def test_configure_cloudflare_stores_verified_credentials(
    session_factory, company_with_budget, monkeypatch
):
    _set_master_key()
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)

    verified: list[tuple[str, str]] = []

    async def _ok(token, account_id):
        verified.append((token, account_id))

    async def _fake_write(db, **kwargs):
        return None

    monkeypatch.setattr("app.integrations.cloudflare.verify_credentials", _ok)
    monkeypatch.setattr("app.services.memory.write", _fake_write)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="configure_integration",
            args={"provider": "cloudflare", "api_token": "cf-tok", "account_id": "acct-1"},
        )
        await db.commit()

    assert outcome.is_error is False
    assert verified == [("cf-tok", "acct-1")]  # verified BEFORE storing
    assert "connect_domain" in outcome.observation
    # The credential is now resolvable for the native hosting/DNS seams.
    async with session_factory() as db:
        creds = await integrations_svc.get_cloudflare(db, company_id=company_id)
    assert creds == ("cf-tok", "acct-1")


@requires_db
async def test_configure_cloudflare_rejects_bad_credentials(
    session_factory, company_with_budget, monkeypatch
):
    _set_master_key()
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)

    from app.integrations.sitehost import SiteHostError

    async def _bad(token, account_id):
        raise SiteHostError("invalid token")

    monkeypatch.setattr("app.integrations.cloudflare.verify_credentials", _bad)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="configure_integration",
            args={"provider": "cloudflare", "api_token": "nope", "account_id": "acct-1"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "rejected" in outcome.observation.lower()
    # Nothing stored when verification fails.
    async with session_factory() as db:
        creds = await integrations_svc.get_cloudflare(db, company_id=company_id)
    assert creds is None


@requires_db
async def test_configure_cloudflare_requires_both_fields(
    session_factory, company_with_budget, monkeypatch
):
    _set_master_key()
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)

    async def _ok(token, account_id):  # pragma: no cover - must not be reached
        raise AssertionError("should not verify without both fields")

    monkeypatch.setattr("app.integrations.cloudflare.verify_credentials", _ok)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="configure_integration",
            args={"provider": "cloudflare", "api_token": "cf-tok"},  # no account_id
        )
        await db.commit()

    assert outcome.is_error is True
    async with session_factory() as db:
        creds = await integrations_svc.get_cloudflare(db, company_id=company_id)
    assert creds is None


@requires_db
async def test_configure_tavily_stores_verified_key(
    session_factory, company_with_budget, monkeypatch
):
    _set_master_key()
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)

    verified: list[str] = []

    async def _ok(api_key):
        verified.append(api_key)

    async def _fake_write(db, **kwargs):
        return None

    monkeypatch.setattr("app.integrations.tavily.verify_credentials", _ok)
    monkeypatch.setattr("app.services.memory.write", _fake_write)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="configure_integration",
            args={"provider": "tavily", "api_key": "tvly-xxx"},
        )
        await db.commit()

    assert outcome.is_error is False
    assert verified == ["tvly-xxx"]  # verified BEFORE storing
    assert "web_search" in outcome.observation
    # The key is now resolvable for the web_search / web_fetch tools.
    from app.services import apikeys

    async with session_factory() as db:
        key = await apikeys.get_plaintext_key(db, company_id=company_id, provider="tavily")
    assert key == "tvly-xxx"


@requires_db
async def test_configure_tavily_rejects_bad_key(session_factory, company_with_budget, monkeypatch):
    _set_master_key()
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)

    from app.integrations.websearch import WebSearchError

    async def _bad(api_key):
        raise WebSearchError("Tavily request failed: 401")

    monkeypatch.setattr("app.integrations.tavily.verify_credentials", _bad)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="configure_integration",
            args={"provider": "tavily", "api_key": "nope"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "rejected" in outcome.observation.lower()
    from app.services import apikeys

    async with session_factory() as db:
        key = await apikeys.get_plaintext_key(db, company_id=company_id, provider="tavily")
    assert key is None  # nothing stored when verification fails


@requires_db
async def test_configure_tavily_requires_api_key(session_factory, company_with_budget, monkeypatch):
    _set_master_key()
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)

    async def _ok(api_key):  # pragma: no cover - must not be reached
        raise AssertionError("should not verify without a key")

    monkeypatch.setattr("app.integrations.tavily.verify_credentials", _ok)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="configure_integration",
            args={"provider": "tavily"},  # no api_key
        )
        await db.commit()

    assert outcome.is_error is True
    from app.services import apikeys

    async with session_factory() as db:
        key = await apikeys.get_plaintext_key(db, company_id=company_id, provider="tavily")
    assert key is None


@requires_db
async def test_configure_integration_unknown_provider(session_factory, company_with_budget):
    company_id = company_with_budget
    agent, task = await _make_task(session_factory, company_id)

    async with session_factory() as db:
        outcome = await execute_tool(
            db,
            _FakeCtx(),
            agent=agent,
            task=task,
            name="configure_integration",
            args={"provider": "salesforce"},
        )
        await db.commit()

    assert outcome.is_error is True
    assert "connect_service" in outcome.observation  # points at the MCP path instead
