"""Offline unit tests for the email seam (no network)."""

from __future__ import annotations

import pytest

from app.integrations.email import (
    EmailError,
    SimulatedEmailSender,
    SmtpEmailSender,
    get_email_sender,
)


@pytest.mark.asyncio
async def test_simulated_is_deterministic_and_offline():
    a = await SimulatedEmailSender().send(to="x@y.com", subject="hi", body="hello")
    b = await SimulatedEmailSender().send(to="x@y.com", subject="hi", body="hello")
    assert a == b
    assert a.provider == "simulated" and a.message_id.startswith("sim:")


def test_resolver_selects_smtp_and_default():
    assert isinstance(get_email_sender("smtp"), SmtpEmailSender)
    assert isinstance(get_email_sender(), SimulatedEmailSender)  # default simulated


@pytest.mark.asyncio
async def test_smtp_without_config_raises_without_network(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    with pytest.raises(EmailError):
        await SmtpEmailSender().send(to="x@y.com", subject="s", body="b")
