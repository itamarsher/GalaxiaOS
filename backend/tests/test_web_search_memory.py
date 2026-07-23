"""Web-search results are filed into shared company memory.

Otherwise a search lives only in the searching agent's transcript, so a sibling
agent (or the next cycle) can't recall it and re-runs the identical query — the
re-search loop seen while dogfooding. Persistence is best-effort: a memory-write
failure must never fail the search itself.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.integrations.websearch import SearchResult
from app.runtime.tools import core
from app.services import memory as memory_svc
from tests.conftest import requires_db

pytestmark = requires_db


class _FakeSearch:
    async def search(self, query, *, max_results=5):
        return [SearchResult(title="MCP Registry", url="https://mcp.example", snippet="stats")]


@pytest.fixture
def _provider(monkeypatch):
    async def _resolve(db, company_id):
        return _FakeSearch(), 0, None, None  # provider, cost=0 (no metering), funding, reason

    monkeypatch.setattr(core, "_resolve_web_search", _resolve)


def _agent_task():
    return SimpleNamespace(id=uuid.uuid4()), SimpleNamespace(
        company_id=uuid.uuid4(), id=uuid.uuid4()
    )


@requires_db
async def test_web_search_files_results_to_memory(session_factory, monkeypatch, _provider):
    calls = {}

    async def _fake_write(db, *, company_id, type, title, content, source_task_id=None, **kw):
        calls.update(title=title, content=content, type=type, company_id=company_id,
                     structured=kw.get("structured"))
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(memory_svc, "write", _fake_write)
    agent, task = _agent_task()
    async with session_factory() as db:
        out = await core._web_search(db, None, agent=agent, task=task, args={"query": "mcp usage"})

    assert "MCP Registry" in out.observation and not out.is_error
    # The findings were filed as a recallable memory titled by the query...
    assert calls["title"] == "Web research: mcp usage"
    assert "MCP Registry" in calls["content"] and calls["company_id"] == task.company_id
    # ...tagged so the TTL reaper can expire stale web findings.
    assert calls["structured"] == {"source": "web_search"}


async def test_purge_ttl_zero_is_a_noop(monkeypatch):
    """TTL 0 disables expiry without touching the DB (guard returns before querying)."""
    deleted = await memory_svc.purge_expired_web_search(
        None, company_id=uuid.uuid4(), older_than_days=0
    )
    assert deleted == 0


@requires_db
async def test_memory_write_failure_never_breaks_the_search(session_factory, monkeypatch, _provider):
    async def _boom(*a, **k):
        raise RuntimeError("embeddings down / table absent")

    monkeypatch.setattr(memory_svc, "write", _boom)
    agent, task = _agent_task()
    async with session_factory() as db:
        out = await core._web_search(db, None, agent=agent, task=task, args={"query": "x"})

    # Persistence is best-effort: the search still returns its results.
    assert "MCP Registry" in out.observation and not out.is_error


@requires_db
async def test_founder_fallback_answer_is_filed_on_resume(session_factory, monkeypatch):
    """The human-backed fallback answer is filed too, so no-provider fleets share it."""
    from app.runtime.tools import chat as tools_chat
    from app.runtime.tools.base import ToolOutcome

    async def _no_provider(db, company_id):
        return None, 0, None, None

    monkeypatch.setattr(core, "_resolve_web_search", _no_provider)
    monkeypatch.setattr(core.settings, "web_search_founder_fallback", True)

    calls = {}

    async def _fake_write(db, *, company_id, type, title, content, source_task_id=None, **kw):
        calls.update(title=title, content=content, structured=kw.get("structured"))
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(memory_svc, "write", _fake_write)

    # 1) First call parks (no answer yet) → nothing filed.
    async def _park(db, ctx, *, agent, task, summary):
        return ToolOutcome(observation="Posted to your DM.", park=True)

    monkeypatch.setattr(tools_chat, "escalate_to_founder", _park)
    agent, task = _agent_task()
    async with session_factory() as db:
        out = await core._web_search(db, None, agent=agent, task=task, args={"query": "mcp"})
    assert out.park and not calls  # parked, nothing filed

    # 2) On resume the founder's reply comes back → it's filed to shared memory.
    async def _answered(db, ctx, *, agent, task, summary):
        return ToolOutcome(observation="Reply in your DM: MCP registry ~20k stars", park=False)

    monkeypatch.setattr(tools_chat, "escalate_to_founder", _answered)
    async with session_factory() as db:
        out = await core._web_search(db, None, agent=agent, task=task, args={"query": "mcp"})
    assert not out.park
    assert calls["title"] == "Web research: mcp" and "20k stars" in calls["content"]
    assert calls["structured"] == {"source": "web_search"}
