"""Independent self-validation critic.

Every substantive thing an agent produces is checked by a critic that is
*independent of the creating agent*: a separate, metered LLM call with its own
system prompt and no access to the agent's reasoning or transcript. The critic
plays **devil's advocate** — it owes the work no benefit of the doubt — and
returns a structured verdict. Its feedback is fed back to the agent, which
iterates until the critic is satisfied or a round cap is hit.

Two entry points, one verdict shape:

- :func:`review_visual` — for **visual outputs** (landing pages, generated
  images). It opinionates on the actual material: a generated image is shown to
  a vision-capable model via an :class:`~app.providers.base.ImageBlock`; a page
  is judged from its self-contained HTML/CSS source (which fully determines how
  it looks). This is what stops the fleet shipping ugly pages and off-brand art.
- :func:`review_output` — a role-aware devil's-advocate pass on a task's final
  result before it counts as done.

Both are **fail-open**: if the critic can't run (no API key, provider error,
malformed verdict) they return ``None`` so the work proceeds unblocked — a
quality gate must never become an availability risk.

This mirrors the existing standalone-LLM pattern in :mod:`app.services.investors`
(personas critiquing a venture), metered through :class:`CostMeter` with
``agent_id``/``task_id`` attribution.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Agent, Task
from app.providers.base import ImageBlock, Message, TextBlock
from app.services import apikeys
from app.services.budget import BudgetExceeded

_log = logging.getLogger("abos.critic")

#: Cap on how much of an HTML/text artifact we hand the critic (keeps the call
#: bounded; a self-contained page's look is decided well within this).
_MAX_ARTIFACT_CHARS = 12_000
#: Output-token ceiling for a verdict — enough for concrete issues + a revision.
_MAX_VERDICT_TOKENS = 900

CRITIC_VERDICT_SCHEMA = {
    "type": "object",
    "properties": {
        "approved": {
            "type": "boolean",
            "description": "True ONLY if a discerning expert would ship this as-is.",
        },
        "score": {
            "type": "integer",
            "minimum": 1,
            "maximum": 10,
            "description": "Overall quality, 1 (unacceptable) to 10 (excellent).",
        },
        "issues": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Specific, concrete problems. Empty only when approving.",
        },
        "revision": {
            "type": "string",
            "description": "One concrete, actionable instruction the agent can follow to fix it.",
        },
    },
    "required": ["approved", "score", "issues", "revision"],
}


@dataclass
class Verdict:
    """A critic's structured judgement of one artifact or result."""

    approved: bool
    score: int
    issues: list[str] = field(default_factory=list)
    revision: str = ""

    def feedback(self) -> str:
        """The critique rendered as an instruction block for the agent to act on."""
        lines = [f"Critic verdict: {'APPROVED' if self.approved else 'NEEDS WORK'} (score {self.score}/10)."]
        if self.issues:
            lines.append("Problems it found:")
            lines.extend(f"- {issue}" for issue in self.issues)
        if self.revision:
            lines.append(f"Do this to fix it: {self.revision}")
        return "\n".join(lines)


def _parse_verdict(raw: str) -> Verdict | None:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or "approved" not in data:
        return None
    issues = data.get("issues") or []
    if not isinstance(issues, list):
        issues = [str(issues)]
    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    return Verdict(
        approved=bool(data.get("approved")),
        score=score,
        issues=[str(i) for i in issues][:12],
        revision=str(data.get("revision") or ""),
    )


def _critic_model(provider) -> str:
    # Planner tier is capable AND vision-capable on every provider; override per
    # deployment with ABOS_CRITIC_MODEL.
    return settings.critic_model or provider.default_models["planner"]


_VISUAL_SYSTEM = (
    "You are an exacting, independent design critic. A company's {role} agent produced "
    "the {kind} below and you are reviewing it BEFORE it goes live. You did not create it "
    "and owe it no loyalty — play devil's advocate. Most first drafts look amateur; hold the "
    "bar of a top-tier designer.\n\n"
    "Judge the actual visual material on: visual hierarchy, layout and spacing (is it cramped "
    "or unbalanced?), typography, colour and contrast (is text readable, is the palette "
    "cohesive and on-brand?), imagery quality, overall polish, and conversion (does the primary "
    "call-to-action stand out?).\n\n"
    "Hold copy to a high marketing bar — this is the #1 reason drafts read as amateur:\n"
    "- BREVITY. A landing page is scannable, not an essay. Reject walls of text, long "
    "paragraphs, and redundant sentences. The hero should land the value in one crisp line; "
    "benefits are tight bullets, not prose. If you could cut half the words and lose nothing, "
    "do NOT approve.\n"
    "- Specific and benefit-led, not vague or buzzword-y ('AI-powered synergy'); every line "
    "earns its place and speaks to the reader's outcome.\n"
    "- Exactly ONE primary call-to-action, unmistakable and above the fold.\n\n"
    "APPROVE only if a discerning designer AND a sharp marketer would ship it unchanged. If "
    "anything looks generic, cluttered, low-contrast, off-brand, unpolished, or wordy, do NOT "
    "approve.\n\n"
    "Return a JSON verdict: approved (bool), score 1-10, issues (specific, concrete design "
    "problems), and revision (one concrete instruction the agent can act on to fix the worst "
    "problems). Be specific enough that the agent can act without seeing your reasoning."
)

_OUTPUT_SYSTEM = (
    "You are an independent devil's-advocate critic. A company's {role} agent is about to "
    "submit the result below for the task goal given. You did not do the work and owe it no "
    "benefit of the doubt — assume it is flawed until proven otherwise. Look for: the goal not "
    "actually met, hand-waving or vague claims, unverified assertions, skipped steps, sloppy or "
    "low-quality work, and anything a demanding reviewer in this role would reject.\n\n"
    "APPROVE only if the result genuinely and fully accomplishes the goal at a high standard. "
    "Otherwise reject with specific, actionable feedback.\n\n"
    "Return a JSON verdict: approved (bool), score 1-10, issues (concrete problems), and "
    "revision (one concrete instruction the agent can act on). Be specific enough that the "
    "agent can improve the work without seeing your reasoning."
)


async def _run(
    db: AsyncSession,
    ctx,
    *,
    company_id,
    agent: Agent,
    task: Task,
    system: str,
    content: list,
) -> Verdict | None:
    """Resolve the provider and make one metered, structured critic call (fail-open)."""
    if not settings.critic_enabled:
        return None
    try:
        resolved = await apikeys.resolve_active_provider(db, company_id=company_id)
        if resolved is None:
            return None
        provider, api_key = resolved.provider, resolved.api_key
        resp = await ctx.cost_meter.run_llm(
            provider,
            api_key=api_key,
            company_id=company_id,
            agent_id=agent.id,
            task_id=task.id,
            model=_critic_model(provider),
            system=system,
            messages=[Message(role="user", content=content)],
            max_tokens=_MAX_VERDICT_TOKENS,
            json_schema=CRITIC_VERDICT_SCHEMA,
            funding_user_id=resolved.funding_user_id,
        )
    except BudgetExceeded:
        # Expected business condition, not a bug -- don't attach a traceback or the
        # root ErrorEscalationHandler will auto-file it as a production error.
        _log.warning("critic call skipped for task %s: budget exceeded", task.id)
        return None
    except Exception:  # noqa: BLE001 - a critic failure must never block the agent
        _log.exception("critic call failed for task %s", task.id)
        return None
    return _parse_verdict(resp.text)


async def review_visual(
    db: AsyncSession,
    ctx,
    *,
    company_id,
    agent: Agent,
    task: Task,
    kind: str,
    brief: str,
    html: str | None = None,
    image: tuple[bytes, str] | None = None,
) -> Verdict | None:
    """Independently critique a visual output, opinionating on the real material.

    Pass ``html`` (a self-contained page's source) or ``image`` (``(bytes,
    mime)`` shown to a vision model) — exactly one. ``brief`` states what the
    artifact is for (goal/title/prompt) so the critique is grounded. Returns the
    :class:`Verdict`, or ``None`` if the critic couldn't run.
    """
    system = _VISUAL_SYSTEM.format(role=agent.role.value, kind=kind)
    content: list = [TextBlock(text=f"This is a {kind}. What it is for:\n{brief.strip()}")]
    if image is not None:
        data, mime = image
        content.append(TextBlock(text="Here is the rendered image — judge how it actually looks:"))
        content.append(
            ImageBlock(data=base64.b64encode(data).decode("ascii"), media_type=mime or "image/png")
        )
    elif html is not None:
        content.append(
            TextBlock(
                text=(
                    "Here is the page's complete, self-contained HTML (inline CSS included) — "
                    "judge how it renders:\n\n" + html[:_MAX_ARTIFACT_CHARS]
                )
            )
        )
    else:  # nothing to look at — don't pretend to critique
        return None
    return await _run(
        db, ctx, company_id=company_id, agent=agent, task=task, system=system, content=content
    )


async def review_output(
    db: AsyncSession,
    ctx,
    *,
    company_id,
    agent: Agent,
    task: Task,
    output: dict,
) -> Verdict | None:
    """Devil's-advocate critique of a task's final result before it counts as done."""
    summary = str((output or {}).get("summary") or "").strip()
    if not summary:
        return None  # nothing substantive to critique
    system = _OUTPUT_SYSTEM.format(role=agent.role.value)
    content = [
        TextBlock(
            text=(
                f"Task goal:\n{(task.goal or '').strip()}\n\n"
                f"Result the {agent.role.value} agent is about to submit:\n"
                f"{summary[:_MAX_ARTIFACT_CHARS]}"
            )
        )
    ]
    return await _run(
        db, ctx, company_id=company_id, agent=agent, task=task, system=system, content=content
    )
