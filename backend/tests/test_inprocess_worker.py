"""The API can fold the arq worker into its own process (free-tier topology)."""

from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main
from app.runtime.worker import WorkerSettings, build_worker


def test_build_worker_uses_worker_settings_without_signal_handlers():
    worker = build_worker(handle_signals=False)
    # Same jobs/crons the standalone worker exposes — one wiring, two topologies.
    names = {f.name for f in worker.functions.values()}
    assert "run_task" in names
    assert len(worker.cron_jobs) == len(WorkerSettings.cron_jobs)


def test_lifespan_is_noop_when_flag_disabled(monkeypatch):
    """With the flag off (production default), no in-process worker is started."""
    monkeypatch.setattr(main.settings, "run_worker_in_process", False)
    started = False

    def _spy(*_a, **_k):  # pragma: no cover - must not be called
        nonlocal started
        started = True
        raise AssertionError("worker should not be built when flag is off")

    monkeypatch.setattr("app.runtime.worker.build_worker", _spy)

    with TestClient(main.create_app()):  # context-manager triggers lifespan
        pass

    assert started is False
