"""Skills loader + MCP tool exposure — pure, DB-free unit tests."""

from __future__ import annotations

from app.models.enums import AgentRole
from app.providers.base import Message, ToolResultBlock, ToolUseBlock
from app.runtime import skills as skills_lib
from app.runtime.backends.native import NativeBackend
from app.services import mcp as mcp_svc


# ── Skills ─────────────────────────────────────────────────────────────────────
def test_skills_load_from_library() -> None:
    names = {s.name for s in skills_lib.all_skills()}
    assert "cold-email-outreach" in names
    skill = skills_lib.get_skill("cold-email-outreach")
    assert skill is not None
    assert skill.title
    assert skill.body  # front matter stripped, body retained


def test_skill_role_scoping() -> None:
    # cold-email-outreach is scoped to growth/ceo, not research.
    growth = {s.name for s in skills_lib.skills_for_role("growth")}
    research = {s.name for s in skills_lib.skills_for_role("research")}
    assert "cold-email-outreach" in growth
    assert "cold-email-outreach" not in research
    # research has its own skill.
    assert "competitor-research" in research


def test_index_for_role_is_nonempty_bullets() -> None:
    idx = skills_lib.index_for_role("ceo")
    assert idx.startswith("- ")


# ── Business-function skill library ─────────────────────────────────────────────
def test_library_has_full_business_function_catalog() -> None:
    # The library ships a broad catalog of business-function playbooks (≥100).
    assert len(skills_lib.all_skills()) >= 100


def test_all_skills_are_wellformed() -> None:
    valid_roles = {r.value for r in AgentRole}
    seen: set[str] = set()
    for s in skills_lib.all_skills():
        assert s.name not in seen, f"duplicate skill name: {s.name}"
        seen.add(s.name)
        assert s.title, f"{s.name}: missing title"
        assert s.description, f"{s.name}: missing description"
        # Rich playbooks, not stubs — front matter stripped, real body retained.
        assert len(s.body) >= 200, f"{s.name}: body too short ({len(s.body)})"
        for role in s.roles:
            assert role in valid_roles, f"{s.name}: unknown role {role!r}"


def test_every_operating_role_has_skills() -> None:
    # Each canonical operating role gets a non-empty skill index (custom is a
    # user-defined catch-all and may legitimately have none of its own).
    for role in AgentRole:
        if role is AgentRole.custom:
            continue
        idx = skills_lib.index_for_role(role.value)
        assert idx.startswith("- "), f"role {role.value} has no skills indexed"


# ── Tool-specific skill catalog ─────────────────────────────────────────────────
# A cross-section of the tool-specific playbooks (Figma, Stripe, Linear, …). These
# teach an agent to drive a named external tool the ABOS way — connect it via MCP
# (`discover_tools`/`use_tool`), escalate with `request_user_action` instead of
# faking a result, and file/record the outcome. A representative sample is asserted
# so a rename or accidental deletion is caught, without pinning the full list.
_TOOL_SKILLS = (
    "figma",
    "canva",
    "webflow",
    "google-ads",
    "meta-ads",
    "mailchimp",
    "hubspot",
    "google-analytics",
    "salesforce",
    "apollo",
    "calendly",
    "stripe",
    "quickbooks",
    "ramp",
    "carta",
    "linear",
    "jira",
    "github",
    "notion",
    "vercel",
    "sentry",
    "posthog",
    "amplitude",
    "snowflake",
    "dbt",
    "bigquery",
    "segment",
    "slack",
    "zapier",
    "docusign",
    "airtable",
    "crunchbase",
    "similarweb",
    # wave 2
    "sketch",
    "miro",
    "loom",
    "hotjar",
    "typeform",
    "tiktok-ads",
    "google-tag-manager",
    "beehiiv",
    "substack",
    "mixpanel",
    "optimizely",
    "launchdarkly",
    "clay",
    "attio",
    "gong",
    "pandadoc",
    "asana",
    "confluence",
    "freshdesk",
    "brex",
    "bill-com",
    "plaid",
    "chargebee",
    "paypal",
    "wise",
    "netsuite",
    "expensify",
    "gitlab",
    "circleci",
    "datadog",
    "pagerduty",
    "cloudflare",
    "aws",
    "netlify",
    "supabase",
    "postman",
    "twilio",
    "looker",
    "tableau",
    "fivetran",
    "databricks",
)


def test_tool_specific_skill_catalog_present() -> None:
    for name in _TOOL_SKILLS:
        skill = skills_lib.get_skill(name)
        assert skill is not None, f"missing tool skill: {name}"
        assert skill.roles, f"{name}: tool skill must be role-scoped"


def test_tool_skills_teach_the_abos_connect_path() -> None:
    # The whole point of a tool skill is the ABOS adaptation: reach the tool through
    # the discovery/hot-load seam rather than assuming a bare integration. Every tool
    # skill must reference that seam and the escalation path when it isn't connected.
    for name in _TOOL_SKILLS:
        skill = skills_lib.get_skill(name)
        assert skill is not None, f"missing tool skill: {name}"
        body = skill.body.lower()
        assert "discover_tools" in body, f"{name}: no discover_tools connect step"
        assert "request_user_action" in body or "request_capability" in body, (
            f"{name}: no escalation path when the tool is not connected"
        )


# ── MCP tool exposure ───────────────────────────────────────────────────────────
def test_mcp_tool_prefix_and_name_normalization() -> None:
    assert mcp_svc.normalize_name("Acme CRM!") == "acme_crm"
    assert mcp_svc.tool_prefix("acme_crm") == "mcp__acme_crm__"


# ── Compaction split helper ──────────────────────────────────────────────────────
def test_compaction_split_lands_on_assistant_turn() -> None:
    # user, (assistant, user)*  — cutting must yield a tail beginning with assistant.
    messages = [Message(role="user", content="seed")]
    for i in range(10):
        messages.append(Message(role="assistant", content=[ToolUseBlock(id=str(i), name="x", input={})]))
        messages.append(Message(role="user", content=[ToolResultBlock(tool_use_id=str(i), content="ok")]))
    split = NativeBackend._safe_compaction_split(messages, keep=4)
    assert split > 0
    assert messages[split].role == "assistant"
