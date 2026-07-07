"""Pure-logic tests for end-of-cycle objective completion.

When a business cycle winds down, any active objective the fleet fully delivered
that cycle is marked ``completed`` (authoritatively, so the dashboard quest board
can clear it). The DB-touching wrapper is a thin query around
:func:`delivered_objective_ids`; these tests pin the linkage/decision rule itself
without a database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services.objectives import delivered_objective_ids, keywords


def _obj(title: str, rationale: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), title=title, rationale=rationale)


def test_keywords_match_decision_inbox_tokenizer() -> None:
    # The quest board and the decision inbox must agree on what links to an
    # objective, so the tokenizer drops the same stopwords/short tokens.
    words = keywords("Launch the email marketing campaign for developers")
    assert "marketing" in words
    assert "developers" in words
    assert "the" not in words
    assert "for" not in words


def test_delivered_when_matched_work_all_succeeded() -> None:
    grow = _obj("Grow developer signups", "Acquire developers through content")
    soc2 = _obj("Achieve SOC2 compliance", "Pass the security audit")
    pricing = _obj("Ship pricing page experiment")
    delivered = delivered_objective_ids(
        [grow, soc2, pricing],
        done_goals=["Write developer signups content article"],
        failed_goals=[],
    )
    assert grow.id in delivered
    assert soc2.id not in delivered  # no matched work
    assert pricing.id not in delivered


def test_failed_matched_task_blocks_completion() -> None:
    soc2 = _obj("Achieve SOC2 security compliance", "Pass the security audit")
    # A done task links to it, but so does a failed one — the work didn't all land.
    delivered = delivered_objective_ids(
        [soc2],
        done_goals=["Prepare security compliance audit checklist"],
        failed_goals=["Security compliance audit remediation stalled"],
    )
    assert soc2.id not in delivered


def test_single_word_overlap_is_below_threshold() -> None:
    soc2 = _obj("Achieve SOC2 compliance", "Pass the security audit")
    # Only "compliance" overlaps — one distinctive word is a weak coincidence.
    delivered = delivered_objective_ids(
        [soc2], done_goals=["review the compliance posture"], failed_goals=[]
    )
    assert soc2.id not in delivered


def test_objective_with_no_distinctive_words_is_skipped() -> None:
    # An objective made entirely of stopwords links to nothing (never auto-closes).
    vague = _obj("the and for", None)
    delivered = delivered_objective_ids(
        [vague], done_goals=["the and for the work"], failed_goals=[]
    )
    assert delivered == []


def test_no_done_work_completes_nothing() -> None:
    obj = _obj("Grow developer signups", "content")
    assert delivered_objective_ids([obj], done_goals=[], failed_goals=[]) == []
