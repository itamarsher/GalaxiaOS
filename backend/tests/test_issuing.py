"""Stripe Issuing: card provisioning, the budget-gated auth webhook, signatures."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

import pytest

from app.integrations.stripe_issuing import StripeIssuingWallet, get_issuing_wallet
from app.integrations.wallet import WalletError
from app.services import issuing as issuing_svc
from tests.conftest import requires_db


def _sign(payload: bytes, secret: str, *, t: int) -> str:
    sig = hmac.new(secret.encode(), f"{t}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={t},v1={sig}"


# ── signature verification (pure) ─────────────────────────────────────────────


def test_verify_signature_accepts_valid_and_rejects_tampering():
    payload = b'{"hello":"world"}'
    header = _sign(payload, "whsec_x", t=1000)
    assert issuing_svc.verify_signature(payload, header, "whsec_x", now=1000) is True
    # Wrong secret, tampered body, and missing pieces all fail closed.
    assert issuing_svc.verify_signature(payload, header, "whsec_other", now=1000) is False
    assert issuing_svc.verify_signature(payload + b"!", header, "whsec_x", now=1000) is False
    assert issuing_svc.verify_signature(payload, "", "whsec_x", now=1000) is False
    assert issuing_svc.verify_signature(payload, header, "", now=1000) is False


def test_verify_signature_rejects_stale_timestamp():
    payload = b"{}"
    header = _sign(payload, "whsec_x", t=1000)
    # 10 minutes of skew is outside the default 300s tolerance.
    assert issuing_svc.verify_signature(payload, header, "whsec_x", now=1600) is False


def test_authorization_field_extraction():
    auth = {"card": {"metadata": {"company_id": "abc"}}, "pending_request": {"amount": 4200}}
    assert issuing_svc.authorization_company_id(auth) == "abc"
    assert issuing_svc.authorization_amount(auth) == 4200
    # Falls back to top-level amount; missing company is None.
    assert issuing_svc.authorization_amount({"amount": 99}) == 99
    assert issuing_svc.authorization_company_id({}) is None


# ── Issuing wallet (pure) ─────────────────────────────────────────────────────


def test_get_issuing_wallet_requires_key(monkeypatch):
    from app.integrations import stripe_issuing

    monkeypatch.setattr(stripe_issuing.settings, "stripe_secret_key", "")
    assert get_issuing_wallet() is None
    monkeypatch.setattr(stripe_issuing.settings, "stripe_secret_key", "sk_test_x")
    assert isinstance(get_issuing_wallet(), StripeIssuingWallet)


async def test_provision_card_requires_cardholder(monkeypatch):
    from app.integrations import stripe_issuing

    monkeypatch.setattr(stripe_issuing.settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(stripe_issuing.settings, "stripe_issuing_cardholder", "")
    with pytest.raises(WalletError):
        await StripeIssuingWallet().provision_card(company_id=uuid.uuid4())


async def test_provision_card_sends_controls_and_metadata(monkeypatch):
    from app.integrations import stripe_issuing

    monkeypatch.setattr(stripe_issuing.settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(stripe_issuing.settings, "stripe_issuing_cardholder", "ich_1")
    monkeypatch.setattr(stripe_issuing.settings, "stripe_currency", "usd")
    cid = uuid.uuid4()
    captured = {}

    async def _stub(method, path, *, data=None):
        captured["method"], captured["path"], captured["data"] = method, path, data
        return {
            "id": "ic_1",
            "last4": "4242",
            "brand": "Visa",
            "exp_month": 12,
            "exp_year": 2030,
            "status": "active",
            "metadata": {"company_id": str(cid)},
        }

    monkeypatch.setattr(stripe_issuing, "stripe_request", _stub)
    card = await StripeIssuingWallet().provision_card(
        company_id=cid, monthly_limit_cents=25_000, allowed_categories=["computer_network_services"]
    )
    assert (captured["method"], captured["path"]) == ("POST", "/v1/issuing/cards")
    d = captured["data"]
    assert d["cardholder"] == "ich_1"
    assert d["type"] == "virtual"
    assert d["spending_controls[spending_limits][0][amount]"] == "25000"
    assert d["spending_controls[spending_limits][0][interval]"] == "monthly"
    assert d["spending_controls[allowed_categories][0]"] == "computer_network_services"
    assert d["metadata[company_id]"] == str(cid)
    assert card.id == "ic_1" and card.last4 == "4242" and card.company_id == str(cid)


async def test_authorize_hits_approve_or_decline(monkeypatch):
    from app.integrations import stripe_issuing

    monkeypatch.setattr(stripe_issuing.settings, "stripe_secret_key", "sk_test_x")
    calls = []

    async def _stub(method, path, *, data=None):
        calls.append(path)
        return {}

    monkeypatch.setattr(stripe_issuing, "stripe_request", _stub)
    await StripeIssuingWallet().authorize("iauth_1", approve=True)
    await StripeIssuingWallet().authorize("iauth_2", approve=False)
    assert calls == [
        "/v1/issuing/authorizations/iauth_1/approve",
        "/v1/issuing/authorizations/iauth_2/decline",
    ]


# ── webhook route (signature gate, no DB) ─────────────────────────────────────


def _client(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setattr("app.config.settings.stripe_webhook_secret", "whsec_test")
    return TestClient(create_app())


def test_webhook_rejects_bad_signature(monkeypatch):
    client = _client(monkeypatch)
    r = client.post(
        "/webhooks/stripe/issuing", content=b"{}", headers={"Stripe-Signature": "t=1,v1=bad"}
    )
    assert r.status_code == 400


def test_webhook_acks_non_authorization_events(monkeypatch):
    client = _client(monkeypatch)
    payload = json.dumps({"type": "ping"}).encode()
    header = _sign(payload, "whsec_test", t=int(time.time()))
    r = client.post(
        "/webhooks/stripe/issuing", content=payload, headers={"Stripe-Signature": header}
    )
    assert r.status_code == 200 and r.json() == {"received": True}


# ── budget gate (DB) ──────────────────────────────────────────────────────────


@requires_db
async def test_decide_authorization_gates_on_budget(session_factory, company_with_budget):
    company_id = company_with_budget  # 10_000c limit, nothing spent/reserved

    def _auth(cid, amount):
        return {
            "card": {"metadata": {"company_id": str(cid)}},
            "pending_request": {"amount": amount},
        }

    async with session_factory() as db:
        # Within headroom -> approve; over the limit -> decline.
        assert await issuing_svc.decide_authorization(db, _auth(company_id, 5_000)) is True
        assert await issuing_svc.decide_authorization(db, _auth(company_id, 10_000)) is True
        assert await issuing_svc.decide_authorization(db, _auth(company_id, 10_001)) is False
        # Unknown company / no metadata / non-positive amount all fail closed.
        assert await issuing_svc.decide_authorization(db, _auth(uuid.uuid4(), 100)) is False
        assert (
            await issuing_svc.decide_authorization(db, {"pending_request": {"amount": 100}})
            is False
        )
        assert await issuing_svc.decide_authorization(db, _auth(company_id, 0)) is False
