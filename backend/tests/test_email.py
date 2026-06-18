"""Offline unit tests for the email seam (no network)."""

from __future__ import annotations

import pytest

from app.integrations.email import (
    EmailError,
    SmtpEmailSender,
    get_email_sender,
)


def test_resolver_selects_smtp_and_default():
    assert isinstance(get_email_sender("smtp"), SmtpEmailSender)
    # No simulated sender: the default resolves to None so send_email reports the
    # capability is unsupported instead of pretending mail was sent.
    assert get_email_sender() is None


@pytest.mark.asyncio
async def test_smtp_without_config_raises_without_network(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    with pytest.raises(EmailError):
        await SmtpEmailSender().send(to="x@y.com", subject="s", body="b")
