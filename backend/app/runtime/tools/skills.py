"""Skill tools: pull a markdown playbook into the loop on demand.

The system prompt only lists a compact *index* of skills (name + description);
the full step-by-step instructions are loaded lazily with ``load_skill`` so the
agent's context stays lean until a skill is actually needed.
"""

from __future__ import annotations

from app.providers.base import ToolSpec
from app.runtime import skills as skills_lib
from app.runtime.tools.base import ToolOutcome

SPECS: list[ToolSpec] = [
    ToolSpec(
        name="load_skill",
        description=(
            "Load a skill — a step-by-step playbook for a common task — by name. "
            "Returns the full instructions to follow. Call this before starting work "
            "a skill covers; the available skill names are listed in your context."
        ),
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "The skill's name (slug)."}},
            "required": ["name"],
        },
    ),
]


async def _load_skill(db, ctx, *, agent, task, args: dict) -> ToolOutcome:
    name = str(args.get("name") or "").strip()
    skill = skills_lib.get_skill(name)
    if skill is None:
        available = ", ".join(s.name for s in skills_lib.all_skills()) or "(none)"
        return ToolOutcome(
            observation=f"No skill named {name!r}. Available skills: {available}.",
            is_error=True,
        )
    # Telemetry: record that this task used this skill so its outcome can later be
    # attributed to the playbook (the transcript is dropped at terminal state).
    # Best-effort — never let a bookkeeping write break the load.
    from app.services import skill_signal

    await skill_signal.record_usage(
        db,
        company_id=task.company_id,
        task_id=task.id,
        agent_id=agent.id,
        skill_name=skill.name,
    )
    return ToolOutcome(observation=f"# Skill: {skill.title}\n\n{skill.body}")


HANDLERS = {"load_skill": _load_skill}
