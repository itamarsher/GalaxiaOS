"""The end-of-cycle retrospective prompt surface — pure, DB-free.

Pins the contract the runtime relies on: the standing agent directive and the CEO
goal both carry the retrospective's shape (right / wrong / suggestions), the quality
bar (prefer NO suggestion over filler), and the CEO's implement-vs-request_capability
fork.
"""

from __future__ import annotations

from app.models.enums import AgentRole
from app.runtime import prompts


def test_agent_loop_prompt_carries_retrospective_and_quality_bar() -> None:
    body = prompts.AGENT_LOOP_SYSTEM.lower()
    assert "retrospective" in body
    # The three parts every retrospective must contain.
    for part in ("went right", "went wrong", "suggestions"):
        assert part in body
    # The explicit quality bar: no suggestion beats filler.
    assert "preferred to suggest no improvement" in body
    assert "bottom of the barrel" in body


def test_ceo_role_owns_ingestion_and_the_implement_or_request_fork() -> None:
    ceo = prompts.ROLE_DESCRIPTIONS[AgentRole.ceo]
    assert "retrospective" in ceo.lower()
    # Ingests, then decides between its own levers and routing a capability request.
    for lever in ("update_company_playbook", "set_agent_directive", "write_memory"):
        assert lever in ceo
    assert "request_capability" in ceo


def test_retrospective_ceo_goal_formats_with_worked_roles() -> None:
    goal = prompts.RETROSPECTIVE_CEO_GOAL.format(roles="growth, research")
    assert "growth, research" in goal
    assert "dispatch_tasks" in goal  # solicit a retro from each agent
    assert "create_report" in goal  # consolidated founder-facing retrospective
    assert "request_capability" in goal
    # No leftover unformatted placeholders.
    assert "{" not in goal and "}" not in goal
