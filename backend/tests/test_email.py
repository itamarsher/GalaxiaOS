"""Offline unit tests for the email seam (no network)."""

from __future__ import annotations

import pytest

from app.integrations.email import (
    EmailError,
    SimulatedEmailSender,
    SmtpEmailSender,
    get_email_sender,
)
from app.integrations.resend import ResendEmailSender


@pytest.mark.asyncio
async def test_simulated_is_deterministic_and_offline():
    a = await SimulatedEmailSender().send(to="x@y.com", subject="hi", body="hello")
    b = await SimulatedEmailSender().send(to="x@y.com", subject="hi", body="hello")
    assert a == b
    assert a.provider == "simulated" and a.message_id.startswith("sim:")


def test_resolver_selects_smtp_and_default():
    assert isinstance(get_email_sender("smtp"), SmtpEmailSender)
    assert isinstance(get_email_sender("resend"), ResendEmailSender)
    assert isinstance(get_email_sender(), SimulatedEmailSender)  # default simulated


@pytest.mark.asyncio
async def test_smtp_without_config_raises_without_network(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    with pytest.raises(EmailError):
        await SmtpEmailSender().send(to="x@y.com", subject="s", body="b")


def test_resend_parse_success_maps_id():
    res = ResendEmailSender._parse_response(200, {"id": "abc-123"})
    assert res.provider == "resend"
    assert res.message_id == "abc-123"


def test_resend_parse_error_surfaces_vendor_message():
    # Unverified/invalid From domain etc. -> vendor message bubbles up verbatim.
    with pytest.raises(EmailError, match="not verified"):
        ResendEmailSender._parse_response(
            403, {"statusCode": 403, "name": "validation_error", "message": "domain not verified"}
        )
    # Defensive: 200 but no id (shouldn't happen) still raises rather than
    # returning an empty message id.
    with pytest.raises(EmailError):
        ResendEmailSender._parse_response(200, {})


@pytest.mark.asyncio
async def test_resend_missing_key_raises_without_network():
    sender = ResendEmailSender(api_key="", sender="me@x.com")  # explicit -> no HTTP
    with pytest.raises(EmailError, match="API key"):
        await sender.send(to="x@y.com", subject="s", body="b")


@pytest.mark.asyncio
async def test_resend_missing_sender_raises_without_network():
    sender = ResendEmailSender(api_key="re_test", sender="")
    with pytest.raises(EmailError, match="Sender address"):
        await sender.send(to="x@y.com", subject="s", body="b")
