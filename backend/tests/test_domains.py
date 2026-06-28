"""Domain integration tests: RDAP mapping, registrars, and metered purchase."""

from __future__ import annotations

import pytest

from app.integrations.availability import interpret_status
from app.integrations.base import RegistrarError
from app.integrations.rdap import RdapRegistrar
from app.integrations.registry import get_registrar
from app.runtime.cost_meter import CostMeter
from app.services import budget as budget_svc
from app.services.budget import BudgetExceeded
from tests.conftest import requires_db

# ── pure ──────────────────────────────────────────────────────────────────────


def test_rdap_status_mapping():
    assert interpret_status(404) is True  # available
    assert interpret_status(200) is False  # taken
    assert interpret_status(429) is None  # unknown
    assert interpret_status(503) is None


async def test_rdap_registrar_unknown_availability_is_not_available(monkeypatch):
    # Simulate RDAP network failure (returns None) -> must NOT be available.
    async def fake_rdap(domain, *, timeout=4.0):
        return None

    monkeypatch.setattr("app.integrations.rdap.rdap_available", fake_rdap)
    q = await RdapRegistrar().check("anything.com")
    assert q.available is False
    with pytest.raises(RegistrarError):
        await RdapRegistrar().register("anything.com")


def test_registry_wiring():
    # No simulated registrar: the default resolves to None so register_domain
    # reports the capability is unsupported instead of faking a registration.
    assert get_registrar("simulated") is None
    assert isinstance(get_registrar("rdap"), RdapRegistrar)
    # namecheap resolves (adapter constructed) but registering without creds raises.
    get_registrar("namecheap")
    from app.integrations.card_checkout import CardCheckoutRegistrar

    assert isinstance(get_registrar("card_checkout"), CardCheckoutRegistrar)
    with pytest.raises(ValueError):
        get_registrar("bogus")


async def test_namecheap_register_without_credentials_raises():
    reg = get_registrar("namecheap")
    with pytest.raises(RegistrarError):
        await reg.register("acme.com")


# ── payment wallet + card-checkout registrar (Stripe Link) ────────────────────


def test_wallet_wiring():
    from app.integrations.stripe_link import StripeLinkWallet
    from app.integrations.wallet import get_wallet

    # Default (none) wires no wallet, so capabilities report unsupported.
    assert get_wallet("none") is None
    assert isinstance(get_wallet("stripe_link"), StripeLinkWallet)
    with pytest.raises(ValueError):
        get_wallet("bogus")


async def test_stripe_link_requires_config():
    # Default settings carry no Stripe keys, so issuing fails loudly rather than
    # fabricating a credential.
    from app.integrations.stripe_link import StripeLinkWallet
    from app.integrations.wallet import WalletError

    with pytest.raises(WalletError):
        await StripeLinkWallet().issue_token(
            amount_cents=1200, currency="usd", merchant_name="m", merchant_url="", context="c"
        )


def test_live_key_refused_in_test_mode(monkeypatch):
    # A live secret key must be refused while the test-mode guard is on, and
    # accepted only when it is explicitly disabled.
    from app.integrations import _stripe

    monkeypatch.setattr(_stripe.settings, "stripe_secret_key", "sk_live_abc")
    monkeypatch.setattr(_stripe.settings, "stripe_test_mode", True)
    with pytest.raises(_stripe.StripeError):
        _stripe._require_secret_key()
    monkeypatch.setattr(_stripe.settings, "stripe_test_mode", False)
    assert _stripe._require_secret_key() == "sk_live_abc"


async def test_card_checkout_requires_wallet(monkeypatch):
    from app.integrations.card_checkout import CardCheckoutRegistrar

    async def _available(domain, *, timeout=4.0):
        return True

    monkeypatch.setattr("app.integrations.card_checkout.rdap_available", _available)
    monkeypatch.setattr("app.integrations.card_checkout.get_wallet", lambda: None)
    with pytest.raises(RegistrarError):
        await CardCheckoutRegistrar().register("acme.com")


async def test_card_checkout_charges_spt_and_registers(monkeypatch):
    """The full agentic flow: mint an SPT, charge it, return the registration."""
    from app.integrations.card_checkout import CardCheckoutRegistrar
    from app.integrations.wallet import IssuedToken

    captured = {}

    class _StubWallet:
        async def issue_token(
            self, *, amount_cents, currency, merchant_name, merchant_url, context
        ):
            captured["amount_cents"] = amount_cents
            return IssuedToken(
                id="spt_test",
                kind="shared_payment_token",
                max_amount_cents=amount_cents,
                currency=currency,
                expires_at=0,
            )

        async def revoke(self, token_id):  # pragma: no cover - not hit on success
            captured["revoked"] = token_id

    async def _available(domain, *, timeout=4.0):
        return True

    async def _stripe_request(method, path, *, data=None):
        captured["charge"] = (method, path, data)
        # Amount charged must not exceed the SPT cap.
        assert int(data["amount"]) <= captured["amount_cents"]
        assert data["payment_method_data[shared_payment_granted_token]"] == "spt_test"
        return {"id": "pi_test", "status": "succeeded", "amount_received": int(data["amount"])}

    monkeypatch.setattr("app.integrations.card_checkout.rdap_available", _available)
    monkeypatch.setattr("app.integrations.card_checkout.get_wallet", lambda: _StubWallet())
    monkeypatch.setattr("app.integrations.card_checkout.stripe_request", _stripe_request)

    reg = await CardCheckoutRegistrar().register("acme.com")
    assert reg.domain == "acme.com"
    assert reg.external_ref == "pi_test"
    assert reg.price_cents == 1200  # .com common price
    assert "revoked" not in captured  # successful charge: credential not revoked


async def test_card_checkout_revokes_token_on_charge_failure(monkeypatch):
    from app.integrations._stripe import StripeError
    from app.integrations.card_checkout import CardCheckoutRegistrar
    from app.integrations.wallet import IssuedToken

    revoked = {}

    class _StubWallet:
        async def issue_token(self, **kw):
            return IssuedToken(
                id="spt_x",
                kind="shared_payment_token",
                max_amount_cents=kw["amount_cents"],
                currency=kw["currency"],
                expires_at=0,
            )

        async def revoke(self, token_id):
            revoked["id"] = token_id

    async def _available(domain, *, timeout=4.0):
        return True

    async def _failing_charge(method, path, *, data=None):
        raise StripeError("card declined")

    monkeypatch.setattr("app.integrations.card_checkout.rdap_available", _available)
    monkeypatch.setattr("app.integrations.card_checkout.get_wallet", lambda: _StubWallet())
    monkeypatch.setattr("app.integrations.card_checkout.stripe_request", _failing_charge)

    with pytest.raises(RegistrarError):
        await CardCheckoutRegistrar().register("acme.com")
    assert revoked["id"] == "spt_x"  # failed charge frees the credential


# ── metered purchase path (DB) ────────────────────────────────────────────────


@requires_db
async def test_metered_external_reserves_then_commits(session_factory, company_with_budget):
    company_id = company_with_budget  # 10_000c limit
    meter = CostMeter(session_factory)

    async def action():
        return 1200, "ref-123", {"domain": "acme.com"}

    ref = await meter.metered_external(
        company_id=company_id,
        agent_id=None,
        task_id=None,
        estimated_cents=1200,
        vendor="registrar(test)",
        sku="acme.com",
        action=action,
    )
    assert ref == "ref-123"
    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_id)
        assert budget.spent_cents == 1200
        assert budget.reserved_cents == 0
        by_cat = await budget_svc.spend_by_category(db, company_id)
    assert by_cat["external"] == 1200


@requires_db
async def test_metered_external_action_failure_releases_reservation(
    session_factory, company_with_budget
):
    company_id = company_with_budget
    meter = CostMeter(session_factory)

    async def failing_action():
        raise RegistrarError("vendor said no")

    with pytest.raises(RegistrarError):
        await meter.metered_external(
            company_id=company_id,
            agent_id=None,
            task_id=None,
            estimated_cents=1200,
            vendor="registrar(test)",
            sku="acme.com",
            action=failing_action,
        )
    async with session_factory() as db:
        budget = await budget_svc.get_active_budget(db, company_id)
        assert budget.spent_cents == 0
        assert budget.reserved_cents == 0  # reservation released, nothing charged


@requires_db
async def test_metered_external_refused_when_over_budget(session_factory, company_with_budget):
    company_id = company_with_budget  # 10_000c
    meter = CostMeter(session_factory)
    called = {"ran": False}

    async def action():
        called["ran"] = True
        return 1, None, None

    with pytest.raises(BudgetExceeded):
        await meter.metered_external(
            company_id=company_id,
            agent_id=None,
            task_id=None,
            estimated_cents=10_001,
            vendor="v",
            sku=None,
            action=action,
        )
    assert called["ran"] is False  # reserved BEFORE the irreversible action
