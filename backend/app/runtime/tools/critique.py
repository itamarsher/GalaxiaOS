"""Visual self-validation gate shared by the content/design tools.

When an agent tries to publish a page or file a generated image, it first passes
through :func:`visual_gate`: an INDEPENDENT critic (see :mod:`app.runtime.critic`)
opinionates on the actual material. If the critic wants changes and the
per-artifact round cap hasn't been hit, the gate hands its feedback back to the
agent (the artifact does NOT go live) so the agent revises and retries — the loop
that runs "until the agent and the critic are happy". Once the critic approves,
or the cap is reached, the gate steps aside and the caller publishes/files.

The per-artifact round counter lives on ``task.input["visual_rounds"][key]`` so
the loop is bounded across the agent's separate tool calls, and is cleared each
time an artifact is accepted so the next one gets a fresh budget.
"""

from __future__ import annotations

from app.config import settings
from app.models import Agent, Task
from app.runtime import critic
from app.runtime.tools.base import ToolOutcome


async def _set_rounds(db, task: Task, key: str, value: int) -> None:
    """Persist the per-artifact round counter (``value <= 0`` clears it)."""
    from app.models import Task as TaskModel

    row = await db.get(TaskModel, task.id)
    if row is None:  # pragma: no cover - defensive
        return
    new_input = dict(row.input or {})
    rounds = dict(new_input.get("visual_rounds") or {})
    if value > 0:
        rounds[key] = value
    else:
        rounds.pop(key, None)
    new_input["visual_rounds"] = rounds
    row.input = new_input
    await db.flush()
    # Keep the in-memory copy consistent for the rest of this step.
    task.input = new_input


async def visual_gate(
    db,
    ctx,
    *,
    agent: Agent,
    task: Task,
    key: str,
    kind: str,
    brief: str,
    html: str | None = None,
    image: tuple[bytes, str] | None = None,
) -> ToolOutcome | None:
    """Run the visual critic; return a "revise" outcome, or ``None`` to proceed.

    ``key`` scopes the round budget (e.g. ``"landing_page"``, ``"image"``).
    Returns a non-terminal :class:`ToolOutcome` telling the agent what to fix when
    the critic rejects the artifact and rounds remain; returns ``None`` when the
    critic approves, is unavailable, or the round cap is exhausted (accept as-is).
    """
    if not settings.critic_enabled:
        return None

    rounds = int((task.input or {}).get("visual_rounds", {}).get(key, 0))
    verdict = await critic.review_visual(
        db,
        ctx,
        company_id=task.company_id,
        agent=agent,
        task=task,
        kind=kind,
        brief=brief,
        html=html,
        image=image,
    )
    if verdict is None or verdict.approved:
        if rounds:
            await _set_rounds(db, task, key, 0)  # accepted — reset for the next artifact
        return None

    if rounds >= settings.visual_critic_max_rounds:
        # Loop exhausted: accept despite residual concerns (earlier rounds already
        # surfaced them) and reset the budget for the next artifact.
        await _set_rounds(db, task, key, 0)
        return None

    await _set_rounds(db, task, key, rounds + 1)
    return ToolOutcome(
        observation=(
            f"HOLD — an independent design critic reviewed this {kind} and it is NOT ready to "
            f"publish yet (round {rounds + 1} of {settings.visual_critic_max_rounds}).\n\n"
            f"{verdict.feedback()}\n\n"
            "Revise the content/design to address this, then call the tool again. It will go "
            "live only once the critic is satisfied (or the revision limit is reached)."
        )
    )
