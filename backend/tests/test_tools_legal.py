"""Tests for the legal tools module (DB-free)."""

from __future__ import annotations

from app.runtime.tools import TOOL_SPECS
from app.runtime.tools.legal import (
    DOC_TYPES,
    HANDLERS,
    SEVERITIES,
    SPECS,
    build_draft,
    scan_compliance,
)

LEGAL_TOOL_NAMES = ("draft_document", "check_compliance", "flag_legal_risk")


def test_legal_tools_registered():
    names = {s.name for s in TOOL_SPECS}
    for expected in LEGAL_TOOL_NAMES:
        assert expected in names


def test_specs_have_object_schema():
    for spec in SPECS:
        assert spec.input_schema["type"] == "object"
        assert "properties" in spec.input_schema


def test_handlers_match_specs():
    assert set(HANDLERS) == {s.name for s in SPECS}


def test_spec_names_are_exactly_assigned():
    assert {s.name for s in SPECS} == set(LEGAL_TOOL_NAMES)


def test_scan_compliance_flags_keyword():
    flags = scan_compliance("This action stores HIPAA-protected records")
    assert "hipaa" in flags


def test_scan_compliance_clean_string_has_no_flags():
    assert scan_compliance("send a friendly welcome email to the team") == []


def test_scan_compliance_is_deterministic_and_sorted():
    flags = scan_compliance("collect payment and pii under gdpr")
    assert flags == sorted(flags)
    assert set(flags) == {"gdpr", "payment", "pii"}


def test_scan_compliance_handles_empty():
    assert scan_compliance("") == []


def test_build_draft_fills_headers_and_terms():
    draft = build_draft("nda", "Acme Corp", ["mutual confidentiality", "2 year term"])
    assert "NON-DISCLOSURE AGREEMENT" in draft
    assert "Acme Corp" in draft
    assert "mutual confidentiality" in draft
    assert "2 year term" in draft
    assert "DRAFT ONLY" in draft


def test_build_draft_placeholders_when_optional_missing():
    draft = build_draft("other", None, None)
    assert "[COUNTERPARTY]" in draft
    assert "[TO BE COMPLETED]" in draft


def test_doc_types_and_severities_match_schema_enums():
    by_name = {s.name: s for s in SPECS}
    assert by_name["draft_document"].input_schema["properties"]["doc_type"]["enum"] == list(
        DOC_TYPES
    )
    assert by_name["flag_legal_risk"].input_schema["properties"]["severity"]["enum"] == list(
        SEVERITIES
    )
