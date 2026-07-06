"""CEO operating-directive tools — DB-free coverage.

Exercises the playbook/directive tools (get/update playbook, set agent directive):
CEO-only gating, validation, and the success paths via lightweight fakes (no DB).
"""

from __future__ import annotations

import uuid

import pytest

from app.models.enums import AgentRole
from app.runtime.prompts import DEFAULT_COMPANY_PLAYBOOK, effective_playbook
from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.team import HANDLERS, SPECS

DIRECTIVE_TOOLS = ("get_company_playbook", "update_company_playbook", "set_agent_directive")


# ─────────────────────────── registration ───────────────────────────


def test_directive_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in DIRECTIVE_TOOLS:
        assert expected in names


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS}


# ─────────────────────────── fakes ───────────────────────────


class _Agent:
    def __init__(self, role=AgentRole.ceo, name="Ada", system_prompt=""):
        self.id = uuid.uuid4()
        self.role = role
        self.name = name
        self.system_prompt = system_prompt


class _Company:
    def __init__(self, playbook=None):
        self.id = uuid.uuid4()
        self.playbook = playbook


class _Task:
    def __init__(self, company_id):
        self.id = uuid.uuid4()
        self.company_id = company_id


class _FakeDB:
    """Returns a fixed company from get(); records flushes; resolves agents via scalars."""

    def __init__(self, company=None, agents=None):
        self.company = company
        self._agents = agents or []
        self.flushed = 0

    async def get(self, model, ident):
        return self.company

    async def flush(self):
        self.flushed += 1

    async def scalars(self, _stmt):
        return _Result(self._agents)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


# ─────────────────────────── CEO gating ───────────────────────────


@pytest.mark.asyncio
async def test_non_ceo_cannot_update_playbook():
    out = await HANDLERS["update_company_playbook"](
        _FakeDB(),
        None,
        agent=_Agent(role=AgentRole.growth),
        task=_Task(uuid.uuid4()),
        args={"playbook": "x" * 20},
    )
    assert out.is_error and "Only the CEO" in out.observation


@pytest.mark.asyncio
async def test_non_ceo_cannot_set_directive():
    out = await HANDLERS["set_agent_directive"](
        _FakeDB(),
        None,
        agent=_Agent(role=AgentRole.finance),
        task=_Task(uuid.uuid4()),
        args={"role": "growth", "directive": "do x"},
    )
    assert out.is_error and "Only the CEO" in out.observation


# ─────────────────────────── playbook read/write ───────────────────────────


@pytest.mark.asyncio
async def test_get_playbook_reports_default_when_unset():
    company = _Company(playbook=None)
    out = await HANDLERS["get_company_playbook"](
        _FakeDB(company), None, agent=_Agent(), task=_Task(company.id), args={}
    )
    assert "platform default" in out.observation
    assert DEFAULT_COMPANY_PLAYBOOK[:40] in out.observation


@pytest.mark.asyncio
async def test_update_playbook_persists_and_takes_effect_for_all():
    company = _Company(playbook=None)
    db = _FakeDB(company)
    out = await HANDLERS["update_company_playbook"](
        db,
        None,
        agent=_Agent(),
        task=_Task(company.id),
        args={"playbook": "Always record real outcomes."},
    )
    assert not out.is_error
    assert company.playbook == "Always record real outcomes."
    assert effective_playbook(company.playbook) == "Always record real outcomes."
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_update_playbook_rejects_empty():
    out = await HANDLERS["update_company_playbook"](
        _FakeDB(_Company()),
        None,
        agent=_Agent(),
        task=_Task(uuid.uuid4()),
        args={"playbook": "   "},
    )
    assert out.is_error and "can't be empty" in out.observation


@pytest.mark.asyncio
async def test_update_playbook_rejects_overlong():
    out = await HANDLERS["update_company_playbook"](
        _FakeDB(_Company()),
        None,
        agent=_Agent(),
        task=_Task(uuid.uuid4()),
        args={"playbook": "x" * 9000},
    )
    assert out.is_error and "too long" in out.observation


# ─────────────────────────── per-agent directive ───────────────────────────


@pytest.mark.asyncio
async def test_set_agent_directive_updates_target_system_prompt():
    company = _Company()
    target = _Agent(role=AgentRole.growth, name="Grow", system_prompt="old")
    db = _FakeDB(company, agents=[target])
    out = await HANDLERS["set_agent_directive"](
        db,
        None,
        agent=_Agent(),
        task=_Task(company.id),
        args={"name": "Grow", "directive": "Own paid acquisition under $5 CAC."},
    )
    assert not out.is_error
    assert target.system_prompt == "Own paid acquisition under $5 CAC."
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_set_agent_directive_rejects_empty():
    out = await HANDLERS["set_agent_directive"](
        _FakeDB(_Company(), agents=[]),
        None,
        agent=_Agent(),
        task=_Task(uuid.uuid4()),
        args={"name": "Grow", "directive": ""},
    )
    assert out.is_error and "can't be empty" in out.observation


@pytest.mark.asyncio
async def test_set_agent_directive_unknown_agent():
    out = await HANDLERS["set_agent_directive"](
        _FakeDB(_Company(), agents=[]),
        None,
        agent=_Agent(),
        task=_Task(uuid.uuid4()),
        args={"name": "Ghost", "directive": "do x"},
    )
    assert out.is_error and "No agent named" in out.observation
