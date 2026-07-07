"""The dispatch-time objective gate: every initiative must be objective-tagged.

`dispatch_task` / `dispatch_tasks` require the CEO to tag each initiative with the
objective it advances (or inherit one from the dispatching task). These tests pin
:func:`_resolve_dispatch_objective` — the rule that decides the tag or asks for a
retry — by stubbing the two objective lookups it makes (no DB).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.runtime.tools import core
from app.services import objectives as objectives_svc


@pytest.fixture
def _stub_objectives(monkeypatch):
    """Return a helper to program the resolver + has_objectives lookups."""

    def program(*, resolved: uuid.UUID | None, has: bool) -> None:
        async def _resolve(db, company_id, handle):
            return resolved

        async def _has(db, company_id):
            return has

        monkeypatch.setattr(objectives_svc, "resolve_objective_id", _resolve)
        monkeypatch.setattr(objectives_svc, "has_objectives", _has)

    return program


def _task(objective_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(company_id=uuid.uuid4(), objective_id=objective_id)


async def test_uses_the_chosen_objective(_stub_objectives) -> None:
    chosen = uuid.uuid4()
    _stub_objectives(resolved=chosen, has=True)
    got = await core._resolve_dispatch_objective(None, _task(), 2)
    assert got == chosen


async def test_inherits_when_no_handle_given(_stub_objectives) -> None:
    inherited = uuid.uuid4()
    _stub_objectives(resolved=None, has=True)
    got = await core._resolve_dispatch_objective(None, _task(objective_id=inherited), None)
    assert got == inherited


async def test_missing_sentinel_when_objectives_exist_and_untagged(_stub_objectives) -> None:
    _stub_objectives(resolved=None, has=True)
    got = await core._resolve_dispatch_objective(None, _task(objective_id=None), None)
    assert got is core._MISSING_OBJECTIVE


async def test_untagged_allowed_when_company_has_no_objectives(_stub_objectives) -> None:
    _stub_objectives(resolved=None, has=False)
    got = await core._resolve_dispatch_objective(None, _task(objective_id=None), None)
    assert got is None
