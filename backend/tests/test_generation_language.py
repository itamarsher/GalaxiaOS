"""The generated company must speak the founder's language deterministically.

Language is detected once (mission → plan, which reads the raw mission) and then
handed by name to every later stage — org design, investor review, refine — so the
whole company lands in one language instead of each stage re-detecting from
derived, JSON-wrapped text and drifting (the org fleet was coming back in French /
English regardless of the mission's language).
"""

from __future__ import annotations

import inspect
import json

from app.runtime.prompts import (
    GENERATION_LANGUAGE_DIRECTIVE,
    MISSION_TO_PLAN_SCHEMA,
    MISSION_TO_PLAN_SYSTEM,
    OPERATING_LANGUAGE_DIRECTIVE,
    generation_language_directive,
    operating_language_directive,
)


# ── the explicit per-venture directive ────────────────────────────────────────
def test_directive_names_the_detected_language():
    d = generation_language_directive("he")
    assert "'he'" in d
    # It must still pin JSON keys to English so parsing/dispatch is unaffected.
    assert "JSON keys" in d
    assert "do not default to english" in d.lower()


def test_directive_falls_back_to_detect_and_mirror_when_unknown():
    # Older drafts (pre-detection) or a detection miss must never regress below the
    # previous baseline: fall back to the generic detect-and-mirror directive.
    for empty in (None, "", "   "):
        assert generation_language_directive(empty) == GENERATION_LANGUAGE_DIRECTIVE


def test_directive_is_per_venture_not_a_hardcoded_example():
    # Each venture gets its OWN language named — the anchoring footgun the investor
    # fix warned about was one hardcoded example shared across every venture.
    assert "'fr'" in generation_language_directive("fr")
    assert "'ja'" in generation_language_directive("ja")
    assert "'fr'" not in generation_language_directive("ja")


# ── the live agent loop is pinned to the detected language too ─────────────────
def test_operating_directive_names_language_or_falls_back():
    d = operating_language_directive("es")
    assert "'es'" in d
    assert "founder's language" in d
    for empty in (None, "", "   "):
        assert operating_language_directive(empty) == OPERATING_LANGUAGE_DIRECTIVE


def test_agent_loop_and_copilot_thread_the_persisted_language():
    # The persisted mission.language must reach every agentic surface, not just
    # onboarding: the live agent loop and the founder-facing copilot/digest.
    from app.runtime.backends import native
    from app.services import copilot

    native_src = inspect.getsource(native)
    assert "mission.language" in native_src
    assert "language=mission_language" in native_src

    answer_src = inspect.getsource(copilot.answer)
    digest_src = inspect.getsource(copilot.generate_digest)
    assert "operating_language_directive(language)" in answer_src
    assert "operating_language_directive(language)" in digest_src


# ── stage 1 detects and reports the language ──────────────────────────────────
def test_mission_to_plan_asks_for_and_schemas_the_language():
    assert "language" in MISSION_TO_PLAN_SYSTEM
    assert "BCP-47" in MISSION_TO_PLAN_SYSTEM
    assert MISSION_TO_PLAN_SCHEMA["properties"]["language"] == {"type": "string"}


# ── the later stages thread the detected language + stop escaping the text ─────
def test_generate_threads_language_into_org_stage():
    from app.services import onboarding

    src = inspect.getsource(onboarding.generate)
    # Language is detected from the plan and stored on the mission…
    assert 'plan.get("language")' in src
    assert "mission.language = language" in src
    # …then handed to the org designer by name, alongside the raw mission, without
    # ascii-escaping the founder's (possibly non-Latin) text.
    assert "generation_language_directive(language)" in src
    assert "ensure_ascii=False" in src
    assert '"mission": mission.raw_text' in src


def test_refine_threads_language():
    from app.services import onboarding

    src = inspect.getsource(onboarding.refine)
    assert "generation_language_directive(language)" in src
    assert "ensure_ascii=False" in src


def test_investor_review_threads_language_and_memo_keeps_unicode():
    from app.services import investors

    review_src = inspect.getsource(investors.review)
    assert "generation_language_directive(" in review_src
    assert "lang_directive" in review_src

    memo_src = inspect.getsource(investors._build_deal_memo)
    assert "ensure_ascii=False" in memo_src
    assert "mission.raw_text" in memo_src


# ── ensure_ascii=False actually preserves the founder's script ────────────────
def test_json_dump_preserves_non_latin_script():
    # The bug: json.dumps defaults to ensure_ascii=True, turning e.g. Hebrew into
    # \\uXXXX escapes that carry no language signal. ensure_ascii=False keeps it.
    hebrew = "בניית מפעל סטארטאפים"
    assert hebrew in json.dumps({"mission": hebrew}, ensure_ascii=False)
    assert hebrew not in json.dumps({"mission": hebrew})  # the old, mangling default
