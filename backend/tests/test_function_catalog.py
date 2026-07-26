"""The business-function catalog — the reusable building blocks (RFC 0002).

Pure catalog data + the selection resolver; no DB, so these always run.
"""

from __future__ import annotations

from app.models.enums import AgentRole
from app.services import function_catalog as fc


def test_catalog_covers_named_blocks_and_maps_to_real_roles():
    keys = {f.key for f in fc.all_functions()}
    for expected in ("website", "social", "outbound", "inbound", "brand",
                     "customer_service", "legal", "finance"):
        assert expected in keys
    for fn in fc.all_functions():
        assert isinstance(fn.role, AgentRole)


def test_selectable_excludes_core_which_is_guaranteed_oversight():
    selectable = {f.key for f in fc.selectable_functions()}
    core = {f.key for f in fc.core_functions()}
    assert selectable.isdisjoint(core)
    assert {"ceo", "governance", "auditor", "data", "platform"} <= core
    assert "ceo" not in selectable  # never an à-la-carte pick


def test_finer_grained_blocks_use_custom_so_they_coexist():
    # custom is never deduped by provision_fleet; dedicated roles are reused.
    for key in ("website", "social", "outbound", "inbound", "customer_service", "legal"):
        assert fc.get(key).role is AgentRole.custom
    assert fc.get("finance").role is AgentRole.finance
    assert fc.get("brand").role is AgentRole.design


def test_functions_are_in_house_first_except_the_genuinely_hard_ones():
    # Keep functions native; billing (payments) is the reserved external case.
    for key in ("website", "social", "outbound", "inbound", "brand",
                "customer_service", "legal", "finance"):
        assert fc.is_in_house(key), f"{key} should be in-house"
    assert not fc.is_in_house("billing")
    assert fc.get("billing").implementation == "external"
    # In-house blocks don't default to external-SaaS connector skills.
    assert "webflow" not in fc.get("website").default_skills
    assert "buffer" not in fc.get("social").default_skills


def test_health_signals_define_the_improvement_target():
    for fn in fc.selectable_functions():
        assert fn.health_signals, f"{fn.key} has no health signals to improve against"
    assert "signup_conversion_rate" in fc.health_signals("website")
    assert fc.health_signals("unknown-key") == ()


def test_spec_for_is_provision_fleet_shaped():
    spec = fc.spec_for("website")
    assert spec["role"] == "custom"
    assert spec["name"] == "Web Presence & Conversion"
    assert spec["autonomy_level"] == "approve_required"
    assert spec["responsibility"]


def test_resolve_selection_dedupes_drops_bogus_and_always_adds_oversight():
    specs = fc.resolve_selection(["website", "website", "finance", "bogus"])
    roles = [s["role"] for s in specs]
    names = [s["name"] for s in specs]
    assert names.count("Web Presence & Conversion") == 1  # duplicate collapsed
    assert "bogus" not in roles  # unknown dropped
    for oversight in ("ceo", "governance", "auditor", "data", "platform"):
        assert oversight in roles


def test_empty_selection_still_launches_a_governed_company():
    roles = [s["role"] for s in fc.resolve_selection([])]
    assert {"ceo", "governance", "auditor", "data", "platform"} <= set(roles)
