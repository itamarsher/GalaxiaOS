"""Skills loader + MCP tool exposure — pure, DB-free unit tests."""

from __future__ import annotations

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
