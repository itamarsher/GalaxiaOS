"""Unit tests for the Metrics API schemas and the business-cycle cron.

No database required — these exercise validation, route registration, the
early-return path of the cron, and the orchestrator entrypoint signature.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest
from pydantic import ValidationError


def test_metric_signal_in_rejects_empty_name():
    from app.schemas.metrics import MetricSignalIn

    with pytest.raises(ValidationError):
        MetricSignalIn(name="", value=1.0)


def test_metric_signal_in_accepts_valid_payload():
    from app.schemas.metrics import MetricSignalIn

    sig = MetricSignalIn(name="mrr", value=1234.5, unit="usd", note="first sale")
    assert sig.name == "mrr"
    assert sig.value == 1234.5
    assert sig.unit == "usd"
    assert sig.note == "first sale"


def _iter_routes(router):
    """Yield concrete routes, descending into included sub-routers.

    Newer FastAPI wraps ``include_router`` results in ``_IncludedRouter``
    objects (``path`` is ``None``); the real routes live on ``original_router``.
    """
    for route in getattr(router, "routes", None) or []:
        original = getattr(route, "original_router", None)
        if original is not None:
            yield from _iter_routes(original)
        else:
            yield route


def test_post_metrics_route_registered():
    import app.main

    paths = {
        getattr(r, "path", None)
        for r in _iter_routes(app.main.app)
        if "POST" in (getattr(r, "methods", None) or set())
    }
    assert "/companies/{company_id}/metrics" in paths


def test_run_business_cycle_skips_when_disabled(monkeypatch):
    from app.config import settings
    from app.jobs import scheduled

    monkeypatch.setattr(settings, "business_cycle_enabled", False)
    result = asyncio.run(scheduled.run_business_cycle({}))
    assert result == {"skipped": True}


def test_create_scheduled_run_is_async():
    from app.runtime import orchestrator

    assert hasattr(orchestrator, "create_scheduled_run")
    assert inspect.iscoroutinefunction(orchestrator.create_scheduled_run)
