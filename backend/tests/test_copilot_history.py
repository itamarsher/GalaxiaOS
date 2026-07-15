"""The founder copilot threads conversation history into the query path.

Regression for: the founder approved a domain purchase with "sounds good" and
the copilot replied about an unrelated two-tier referral program. The ask was
stateless — no prior turns reached the model — so a terse follow-up retrieved an
irrelevant memory and the model confabulated from it. These tests pin the fix:
prior turns are sanitized, folded into memory retrieval, and passed to the LLM.
"""

from __future__ import annotations

import inspect

from app.providers.base import Message
from app.services import copilot


def test_recent_history_sanitizes_roles_and_drops_empties():
    turns = [
        {"role": "user", "content": "buy galaxiaos.com"},
        {"role": "assistant", "content": "here's the plan"},
        {"role": "system", "content": "  "},  # empty after strip -> dropped
        {"role": "weird", "content": "kept as user"},  # unknown role -> user
    ]
    msgs = copilot._recent_history(turns)
    assert [(m.role, m.content) for m in msgs] == [
        ("user", "buy galaxiaos.com"),
        ("assistant", "here's the plan"),
        ("user", "kept as user"),
    ]


def test_recent_history_caps_turn_count_and_length():
    turns = [{"role": "user", "content": f"m{i}"} for i in range(50)]
    msgs = copilot._recent_history(turns)
    assert len(msgs) == copilot._HISTORY_TURNS
    assert msgs[-1].content == "m49"  # keeps the most recent

    long = copilot._recent_history([{"role": "user", "content": "x" * 5000}])
    assert len(long[0].content) == copilot._HISTORY_CHAR_CAP


def test_recent_history_accepts_message_objects_and_handles_none():
    assert copilot._recent_history(None) == []
    msgs = copilot._recent_history([Message(role="assistant", content="hi")])
    assert msgs[0].role == "assistant" and msgs[0].content == "hi"


def test_retrieval_text_folds_in_prior_user_turn():
    prior = [
        Message(role="user", content="should we buy the galaxiaos.com domain?"),
        Message(role="assistant", content="a domain purchase is outside my actions..."),
    ]
    # A bare affirmation must inherit the topic it is responding to, so memory
    # retrieval surfaces the domain thread rather than a random initiative.
    text = copilot._retrieval_text(prior, "sounds good")
    assert "galaxiaos.com" in text and "sounds good" in text

    # With no prior context, retrieval falls back to the question itself.
    assert copilot._retrieval_text([], "what's our spend?") == "what's our spend?"


def test_answer_threads_history_into_retrieval_and_messages():
    # Source-level guard: the query path must retrieve on the composed history
    # text and prepend the prior turns to the LLM messages, not send the bare
    # question. Pins the wiring against a silent regression to statelessness.
    src = inspect.getsource(copilot.answer)
    assert "_recent_history(history)" in src
    assert "_retrieval_text(prior, question)" in src
    assert "*prior" in src
