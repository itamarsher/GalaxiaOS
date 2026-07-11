"""Tests for the ephemeral live Mission Log (service + agent tool)."""

from __future__ import annotations

import uuid

import pytest

from app.config import settings
from app.models import Agent, AgentRun, Task
from app.models.enums import AgentRole, RunStatus, RunTrigger, TaskStatus
from app.runtime.tools import CORE_TOOL_NAMES, TOOL_SPECS, execute_tool
from app.services import mission_log
from tests.conftest import requires_db


# ── A tiny in-memory stand-in for redis.asyncio (no server needed) ────────────
class _FakePipeline:
    def __init__(self, store: dict):
        self._store = store
        self._ops: list = []

    def lpush(self, key, val):
        self._ops.append(("lpush", key, val))
        return self

    def ltrim(self, key, start, end):
        self._ops.append(("ltrim", key, start, end))
        return self

    def expire(self, key, ttl):
        self._ops.append(("expire", key, ttl))
        return self

    async def execute(self):
        for op in self._ops:
            if op[0] == "lpush":
                self._store.setdefault(op[1], []).insert(0, op[2])
            elif op[0] == "ltrim":
                _, key, start, end = op
                self._store[key] = self._store.get(key, [])[start : end + 1]
        self._ops = []
        return True


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, list] = {}

    def pipeline(self):
        return _FakePipeline(self.store)

    async def lrange(self, key, start, end):
        vals = self.store.get(key, [])
        return vals[start:] if end == -1 else vals[start : end + 1]


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(mission_log, "_client", fake)
    yield fake
    monkeypatch.setattr(mission_log, "_client", None)


# ── DB-free unit tests ────────────────────────────────────────────────────────
def test_post_mission_update_is_a_core_tool():
    assert "post_mission_update" in CORE_TOOL_NAMES
    spec = next((s for s in TOOL_SPECS if s.name == "post_mission_update"), None)
    assert spec is not None
    assert spec.input_schema["required"] == ["headline"]


async def test_record_keeps_newest_and_caps(fake_redis):
    cid = uuid.uuid4()
    for i in range(settings.mission_log_max_entries + 5):
        await mission_log.record(
            cid, agent_id=uuid.uuid4(), agent_name="Growth", role="growth", headline=f"m{i}"
        )
    got = await mission_log.recent(cid)
    # Capped at the configured max, newest first.
    assert len(got) == settings.mission_log_max_entries
    assert got[0]["headline"] == f"m{settings.mission_log_max_entries + 4}"
    assert got[0]["kind"] == "update"
    assert got[0]["role"] == "growth"


async def test_record_empty_headline_is_dropped(fake_redis):
    cid = uuid.uuid4()
    assert await mission_log.record(cid, agent_id=None, agent_name="A", role=None, headline="   ") is None
    assert await mission_log.recent(cid) == []


async def test_record_clips_long_headline(fake_redis):
    cid = uuid.uuid4()
    entry = await mission_log.record(
        cid, agent_id=None, agent_name="A", role="ceo", headline="x" * 500
    )
    assert entry is not None
    assert len(entry["headline"]) <= settings.mission_log_headline_max_chars


async def test_recent_is_empty_when_redis_unavailable(monkeypatch):
    # A dead Redis must degrade to [] rather than raise into the event stream.
    class _Boom:
        async def lrange(self, *a, **k):
            raise ConnectionError("down")

    monkeypatch.setattr(mission_log, "_client", _Boom())
    assert await mission_log.recent(uuid.uuid4()) == []
    monkeypatch.setattr(mission_log, "_client", None)


# ── DB-backed integration: the agent tool posts through to the log ────────────
@requires_db
async def test_post_mission_update_tool_records(session_factory, company_with_budget, fake_redis):
    company_id = company_with_budget
    async with session_factory() as db:
        agent = Agent(company_id=company_id, role=AgentRole.growth, name="Ada")
        db.add(agent)
        await db.flush()
        run = AgentRun(
            company_id=company_id, trigger=RunTrigger.scheduled, status=RunStatus.running
        )
        db.add(run)
        await db.flush()
        run.root_run_id = run.id
        task = Task(
            company_id=company_id,
            run_id=run.id,
            root_run_id=run.id,
            agent_id=agent.id,
            goal="launch outreach",
            status=TaskStatus.running,
        )
        db.add(task)
        await db.commit()

        out = await execute_tool(
            db,
            object(),
            agent=agent,
            task=task,
            name="post_mission_update",
            args={"headline": "Launched cold outreach to 40 prospects", "detail": "first wave"},
        )
    assert not out.is_error

    got = await mission_log.recent(company_id)
    assert len(got) == 1
    assert got[0]["headline"] == "Launched cold outreach to 40 prospects"
    assert got[0]["detail"] == "first wave"
    assert got[0]["agent_name"] == "Ada"
    assert got[0]["kind"] == "update"
