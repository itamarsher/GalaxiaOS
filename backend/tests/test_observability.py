"""ErrorEscalationHandler: escalates unexpected errors, skips expected ones."""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.observability import ErrorEscalationHandler
from app.providers.base import ProviderError
from app.services.budget import BudgetExceeded


def _record_with_exc(exc: BaseException, logger_name: str = "arq.worker") -> logging.LogRecord:
    try:
        raise exc
    except BaseException:
        record = logging.LogRecord(
            name=logger_name, level=logging.ERROR, pathname=__file__, lineno=1,
            msg="run_task failed", args=(), exc_info=__import__("sys").exc_info(),
        )
    return record


@pytest.fixture
def reported(monkeypatch):
    calls: list[str] = []

    async def _fake_report_code_error(*, error_type, **_kwargs):
        calls.append(error_type)

    from app.services import error_monitor

    monkeypatch.setattr(error_monitor, "report_code_error", _fake_report_code_error)
    return calls


@pytest.mark.asyncio
async def test_provider_error_is_not_escalated(reported):
    ErrorEscalationHandler().emit(_record_with_exc(ProviderError("insufficient credits", kind="bad_request")))
    await asyncio.sleep(0)
    assert reported == []


@pytest.mark.asyncio
async def test_budget_exceeded_is_not_escalated(reported):
    ErrorEscalationHandler().emit(_record_with_exc(BudgetExceeded("company", 100, 0)))
    await asyncio.sleep(0)
    assert reported == []


@pytest.mark.asyncio
async def test_unexpected_error_is_escalated(reported):
    ErrorEscalationHandler().emit(_record_with_exc(ValueError("boom")))
    await asyncio.sleep(0)
    assert reported == ["ValueError"]
