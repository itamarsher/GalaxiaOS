"""Founder connection tokens: a stateless per-user HMAC credential for the Founder MCP."""

from __future__ import annotations

import uuid

import pytest

from app.services import founder_token


def test_mint_verify_round_trip(monkeypatch):
    monkeypatch.setattr(founder_token.settings, "founder_connection_secret", "s3cr3t")
    uid = uuid.uuid4()
    token = founder_token.mint(user_id=uid)
    assert founder_token.verify(token) == uid


def test_tampered_or_foreign_token_is_rejected(monkeypatch):
    monkeypatch.setattr(founder_token.settings, "founder_connection_secret", "s3cr3t")
    token = founder_token.mint(user_id=uuid.uuid4())
    assert founder_token.verify(token + "x") is None  # bad signature
    assert founder_token.verify("garbage") is None
    # A token signed with a different secret must not verify.
    monkeypatch.setattr(founder_token.settings, "founder_connection_secret", "other")
    assert founder_token.verify(token) is None


def test_disabled_when_secret_unset(monkeypatch):
    monkeypatch.setattr(founder_token.settings, "founder_connection_secret", "")
    with pytest.raises(founder_token.TokensDisabled):
        founder_token.mint(user_id=uuid.uuid4())
    assert founder_token.verify("anything.anything") is None
