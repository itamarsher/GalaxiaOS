"""Decision chat carries the prior thread into the agent's context.

Regression guard: ``discuss_decision`` used to build a single stateless user
turn, so a multi-turn back-and-forth lost all earlier messages. These verify the
prior turns are replayed as real conversation turns (with the right roles),
framed by a briefing turn, with the new question last — without standing up a
provider or a database (both are stubbed).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.api.decisions import _load_thread
from app.providers.base import LLMResponse
from app.services import copilot


def _stub_llm(monkeypatch) -> dict:
    """Stub provider resolution, company state, and the metered LLM call.

    Returns a dict that captures the ``messages`` handed to the model.
    """
    captured: dict = {}
    provider = SimpleNamespace(name="fake", default_models={"cheap": "m"})

    async def fake_resolve(db, *, company_id):
        return (provider, "key")

    async def fake_state(db, company_id):
        return "STATE"

    class _FakeMeter:
        def __init__(self, *a, **k):
            pass

        async def run_llm(self, prov, **kwargs):
            captured["messages"] = kwargs["messages"]
            return LLMResponse(text="ok", tool_calls=[])

    monkeypatch.setattr(copilot.apikeys, "resolve_provider", fake_resolve)
    monkeypatch.setattr(copilot, "_company_state", fake_state)
    monkeypatch.setattr(copilot, "CostMeter", _FakeMeter)
    return captured


def _decision() -> SimpleNamespace:
    return SimpleNamespace(
        agent_id=None,
        kind=SimpleNamespace(value="spend_approval"),
        summary="Buy domain",
        payload={"tool": "register_domain"},
    )


async def test_discuss_decision_replays_history(monkeypatch) -> None:
    captured = _stub_llm(monkeypatch)
    history = [
        SimpleNamespace(who="you", text="why this domain?"),
        SimpleNamespace(who="agent", text="it matches the brand"),
    ]

    answer = await copilot.discuss_decision(
        db=None,
        company_id=uuid.uuid4(),
        decision=_decision(),
        message="and the cost?",
        history=history,
    )

    assert answer == "ok"
    msgs = captured["messages"]
    # briefing(user) + ack(assistant) + 2 replayed turns + the new question
    assert [m.role for m in msgs] == ["user", "assistant", "user", "assistant", "user"]
    assert "Company state:\nSTATE" in msgs[0].content
    assert msgs[2].content == "why this domain?"
    assert msgs[3].content == "it matches the brand"
    assert msgs[4].content == "and the cost?"


async def test_discuss_decision_without_history_is_single_question(monkeypatch) -> None:
    captured = _stub_llm(monkeypatch)

    await copilot.discuss_decision(
        db=None, company_id=uuid.uuid4(), decision=_decision(), message="why?"
    )

    msgs = captured["messages"]
    # Just the briefing + ack + the question (no replayed turns).
    assert [m.role for m in msgs] == ["user", "assistant", "user"]
    assert msgs[-1].content == "why?"


async def test_discuss_decision_caps_history(monkeypatch) -> None:
    captured = _stub_llm(monkeypatch)
    history = [SimpleNamespace(who="you", text=f"q{i}") for i in range(40)]

    await copilot.discuss_decision(
        db=None, company_id=uuid.uuid4(), decision=_decision(), message="latest", history=history
    )

    replayed = [m for m in captured["messages"][2:-1]]
    assert len(replayed) == copilot._DECISION_CHAT_HISTORY_LIMIT
    # Oldest turns are dropped; the most recent are kept.
    assert replayed[-1].content == "q39"


def test_load_thread_parses_persisted_turns() -> None:
    decision = SimpleNamespace(chat=[{"who": "you", "text": "hi"}, {"who": "agent", "text": "hey"}])
    assert [(t.who, t.text) for t in _load_thread(decision)] == [("you", "hi"), ("agent", "hey")]


def test_load_thread_empty() -> None:
    assert _load_thread(SimpleNamespace(chat=None)) == []
    assert _load_thread(SimpleNamespace(chat=[])) == []
