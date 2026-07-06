"""Pure-logic tests for the decision-inbox context enrichment (Task 2).

The decision inbox surfaces the bigger picture — which objective a decision
relates to — by best-effort keyword overlap, since tasks carry no explicit
objective foreign key. These tests pin that matching down without a DB.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.api.decisions import _best_objective, _keywords


def _obj(title: str, rationale: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(title=title, rationale=rationale)


def test_keywords_drop_stopwords_and_short_tokens() -> None:
    words = _keywords("Launch the email marketing campaign for developers")
    assert "marketing" in words
    assert "developers" in words
    # Stopwords and short tokens are excluded.
    assert "the" not in words
    assert "for" not in words


def test_best_objective_picks_strongest_overlap() -> None:
    objectives = [
        _obj("Grow developer signups", "Acquire developers through content"),
        _obj("Achieve SOC2 compliance", "Pass the security audit"),
    ]
    match = _best_objective(
        _keywords("Run a developer signups acquisition content push"), objectives
    )
    assert match == "Grow developer signups"


def test_best_objective_requires_two_overlapping_words() -> None:
    objectives = [_obj("Achieve SOC2 compliance", "Pass the security audit")]
    # Only one distinctive word ("compliance") overlaps -> below threshold.
    assert _best_objective(_keywords("review the compliance posture"), objectives) is None


def test_best_objective_none_when_no_objectives() -> None:
    assert _best_objective(_keywords("anything at all here"), []) is None
