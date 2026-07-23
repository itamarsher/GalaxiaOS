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
        calls.update(title=title, content=content, type=type, company_id=company_id)
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(memory_svc, "write", _fake_write)
    agent, task = _agent_task()
    async with session_factory() as db:
        out = await core._web_search(db, None, agent=agent, task=task, args={"query": "mcp usage"})

    assert "MCP Registry" in out.observation and not out.is_error
    # The findings were filed as a recallable memory titled by the query.
    assert calls["title"] == "Web research: mcp usage"
    assert "MCP Registry" in calls["content"] and calls["company_id"] == task.company_id


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
