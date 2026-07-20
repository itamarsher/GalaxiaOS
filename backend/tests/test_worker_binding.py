"""Default worker binding + per-tenant persona identity (RFC 0001 §5 / §6)."""

from __future__ import annotations

import uuid

from app.config import settings
from app.models.enums import AgentBackendType, AgentRole
from app.runtime.backends.openclaw_worker import OpenClawWorker
from app.services import business_function, worker_binding


def _mandate(company_id, function="growth") -> business_function.Mandate:
    return business_function.Mandate(
        company_id=company_id, function=function, function_title="Growth Lead",
        mission="m", language=None, objectives="", metrics="", constraints=[],
        budget=business_function.BudgetEnvelope(),
    )


def test_default_backend_native_unless_gateway_configured(monkeypatch):
    # Default is native for everyone.
    monkeypatch.setattr(settings, "default_agent_backend", "native")
    monkeypatch.setattr(settings, "openclaw_base_url", "https://gw.example")
    assert worker_binding.default_backend_for(AgentRole.growth) is AgentBackendType.native
    assert worker_binding.default_backend_for(AgentRole.ceo) is AgentBackendType.native


def test_default_backend_external_binds_functions_but_never_the_ceo(monkeypatch):
    monkeypatch.setattr(settings, "default_agent_backend", "external")
    monkeypatch.setattr(settings, "openclaw_base_url", "https://gw.example")
    # A generated function auto-binds to the managed Gateway…
    assert worker_binding.default_backend_for(AgentRole.growth) is AgentBackendType.external
    # …but the CEO always runs natively (it orchestrates the company).
    assert worker_binding.default_backend_for(AgentRole.ceo) is AgentBackendType.native


def test_default_external_falls_back_to_native_without_a_gateway(monkeypatch):
    # 'external' with no Gateway bound would strand agents with no worker — so the
    # helper degrades to native rather than generating unrunnable functions.
    monkeypatch.setattr(settings, "default_agent_backend", "external")
    monkeypatch.setattr(settings, "openclaw_base_url", "")
    assert worker_binding.default_backend_for(AgentRole.growth) is AgentBackendType.native


def test_persona_route_is_scoped_per_tenant():
    # The same role in two companies routes to two DISTINCT personas (no leak).
    worker = OpenClawWorker(base_url="https://gw", api_key="k")
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    r1 = worker._route(_mandate(c1))
    r2 = worker._route(_mandate(c2))
    assert r1 == f"openclaw/{c1}:growth"
    assert r1 != r2  # same "growth" role, different companies => different personas


def test_explicit_model_overrides_the_route():
    worker = OpenClawWorker(base_url="https://gw", api_key="k", model="anthropic/claude")
    assert worker._route(_mandate(uuid.uuid4())) == "anthropic/claude"
