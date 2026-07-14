"""Skill optimizer — SkillOpt-style, validation-gated, bounded skill edits.

Ports the idea behind Microsoft's *SkillOpt* onto GalaxiaOS's own machinery: treat
a skill's markdown file as the trainable state of the (frozen) agents, and improve
it from real outcomes rather than a one-shot rewrite. Each candidate is accepted
only if it beats the current playbook on an independent review — the *validation
gate* that keeps the library from drifting.

The loop, per underperforming skill (chosen by :mod:`app.services.skill_signal`):

1. **Reflect + bounded edit.** One metered optimizer call (through the mandatory
   ``CostMeter`` chokepoint, like :mod:`app.runtime.critic`) sees the *whole* skill
   file — front matter and body, because the ``description`` trigger matters as much
   as the steps — plus the ``writing-great-skills`` rubric and concrete evidence of
   where agents using it failed. It returns a revised file and a bounded list of
   changes (clipped to a learning-rate budget).
2. **Validation gate.** A second, independent call adjudicates current (A) vs
   candidate (B) against the same failure evidence and rubric. The candidate is
   accepted only when B wins by at least a margin.
3. **Propose.** An accepted candidate is filed as a tracker issue whose body carries
   the exact file path and full new content — flowing into the same
   triage → implement → CI → auto-merge pipeline a ``request_capability`` uses, so a
   validated skill edit reviews-and-merges itself (a slim-margin one is flagged for a
   human instead). Nothing on disk is touched here; the change lands only when that
   PR merges and the worker reindexes the library at import.

Fail-open and bounded throughout: a model or budget error just means "no proposal
this tick", never a raised exception into the cron.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.integrations.issues import IssueTracker, IssueTrackerError
from app.models.enums import AgentRole, MemoryType
from app.observability import get_logger
from app.providers.base import Message, TextBlock
from app.runtime import skills as skills_lib
from app.services import apikeys
from app.services import skill_signal as signal_svc
from app.services.skill_signal import SkillSignal

_log = get_logger("abos.skill_optimizer")

_VALID_ROLES = {r.value for r in AgentRole}
#: A candidate must still look like a real skill (mirrors the test-suite bar in
#: ``test_skills_and_mcp.py``): a description trigger and a non-trivial body.
_MIN_BODY_CHARS = 200

_MAX_REFLECT_TOKENS = 4000
_MAX_GATE_TOKENS = 700

REFLECT_SCHEMA = {
    "type": "object",
    "properties": {
        "revised_skill": {
            "type": "string",
            "description": (
                "The FULL revised skill file: the '---' front matter (name, title, "
                "description, roles) followed by the markdown body. Not a diff — the "
                "complete file, ready to save verbatim."
            ),
        },
        "changes": {
            "type": "array",
            "items": {"type": "string"},
            "description": "One short line per discrete change you made. Keep it bounded.",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "How likely this revision actually fixes the failures, 0-1.",
        },
        "rationale": {
            "type": "string",
            "description": "Why these changes address the observed failures.",
        },
    },
    "required": ["revised_skill", "changes", "confidence", "rationale"],
}

GATE_SCHEMA = {
    "type": "object",
    "properties": {
        "winner": {
            "type": "string",
            "enum": ["A", "B", "tie"],
            "description": "Which playbook better fixes the failures and follows the rubric.",
        },
        "margin": {
            "type": "integer",
            "minimum": 0,
            "maximum": 10,
            "description": "How much better the winner is: 0 (indistinguishable) to 10 (decisive).",
        },
        "rationale": {"type": "string"},
    },
    "required": ["winner", "margin", "rationale"],
}

_REFLECT_SYSTEM = (
    "You are a skill optimizer for a fleet of autonomous business agents. A skill is a "
    "markdown playbook agents load on demand; you improve one from evidence of where it "
    "failed. You are given the CURRENT skill file, the shared authoring rubric, and real "
    "failing tasks that used it.\n\n"
    "Rewrite the skill file to fix the observed failure modes and better satisfy the rubric. "
    "Make BOUNDED changes — at most {max_edits} discrete edits — and keep the body tight: this "
    "whole file loads on every use, so add only what the common path needs and cut anything "
    "that no longer earns its place. Preserve the '---' front matter (name, title, description, "
    "roles); sharpen the description trigger and role scope if that is where the failure is. Do "
    "NOT invent tools or capabilities the agents don't have. If the skill is already good and "
    "the failures are not its fault, return it essentially unchanged with an empty change list.\n\n"
    "Return the FULL revised file (front matter + body), a short list of the changes you made, "
    "your confidence (0-1), and a one-paragraph rationale."
)

_GATE_SYSTEM = (
    "You are an independent, skeptical reviewer — the validation gate for a skill-library "
    "change. You did not write either version and owe neither the benefit of the doubt. Two "
    "versions of the same skill playbook follow, A (current) and B (proposed), plus the real "
    "failures that motivated the change and the authoring rubric.\n\n"
    "Decide which version would better prevent those failures and better follows the rubric "
    "(a sharp trigger, tight body, one clear job, no invented capabilities). Prefer A unless B "
    "is genuinely better — a change that only churns wording or adds bloat should NOT win. "
    "Return the winner (A, B, or tie), a margin 0-10 for how decisive it is, and your rationale."
)


@dataclass(frozen=True)
class SkillProposal:
    """A gated, ready-to-file improvement to one skill file."""

    skill_name: str
    title: str
    repo_path: str  # e.g. backend/app/runtime/skills/library/github.md
    new_text: str  # the complete new file (front matter + body)
    changes: list[str]
    rationale: str
    gate_margin: int
    confidence: str  # "high" (auto-merge path) | "low" (flag for a human)
    signal: SkillSignal


def _model(provider) -> str:
    return settings.skill_optimize_model or provider.default_models["planner"]


def _evidence(skill, signal: SkillSignal) -> str:
    """Render a skill's failure evidence as the optimizer/gate user prompt tail."""
    lines = [
        f"Skill: {skill.name} — {skill.title}",
        (
            f"Recent signal: {signal.success_count}/{signal.sample_count} tasks succeeded "
            f"({signal.success_rate:.0%} success) across {signal.sample_count} uses."
        ),
    ]
    if signal.failures:
        lines.append("\nFailing tasks that loaded this skill:")
        for i, f in enumerate(signal.failures, 1):
            detail = f.detail or "(no detail recorded)"
            lines.append(f"{i}. Goal: {f.goal}\n   Outcome: {detail}")
    else:
        lines.append("\n(No per-task failure detail was retained; optimize against the rubric.)")
    return "\n".join(lines)


async def _complete_json(
    ctx,
    *,
    resolved: apikeys.ResolvedProvider,
    company_id: uuid.UUID,
    system: str,
    user_text: str,
    schema: dict,
    max_tokens: int,
) -> dict | None:
    """One metered, structured optimizer call (fail-open, returns parsed JSON)."""
    try:
        resp = await ctx.cost_meter.run_llm(
            resolved.provider,
            api_key=resolved.api_key,
            company_id=company_id,
            agent_id=None,
            task_id=None,
            model=_model(resolved.provider),
            system=system,
            messages=[Message(role="user", content=[TextBlock(text=user_text)])],
            max_tokens=max_tokens,
            json_schema=schema,
            funding_user_id=resolved.funding_user_id,
        )
    except Exception:  # noqa: BLE001 — a failed optimizer call just means "no proposal"
        _log.exception(
            "skill_optimizer_llm_failed", extra={"extra_fields": {"company": str(company_id)}}
        )
        return None
    try:
        data = json.loads(resp.text)
    except (json.JSONDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _valid_candidate(text: str, *, skill_name: str, current_text: str) -> bool:
    """A candidate must be a well-formed, changed skill file (loader's own rules)."""
    text = (text or "").strip()
    if not text or text == (current_text or "").strip():
        return False
    parsed = skills_lib.parse_skill_text(text, default_name=skill_name)
    if not parsed.description or len(parsed.body) < _MIN_BODY_CHARS:
        return False
    if any(r not in _VALID_ROLES for r in parsed.roles):
        return False
    return True


async def optimize_skill(
    ctx,
    *,
    company_id: uuid.UUID,
    resolved: apikeys.ResolvedProvider,
    skill,
    current_text: str,
    signal: SkillSignal,
) -> SkillProposal | None:
    """Reflect → bounded edit → validation gate for one skill. ``None`` = no change.

    Pure of the DB — both model calls go through ``ctx.cost_meter`` (its own
    sessions), so this is unit-testable with a stub cost meter.
    """
    rubric = skills_lib.get_skill("writing-great-skills")
    rubric_text = rubric.body if rubric else ""
    evidence = _evidence(skill, signal)
    max_edits = settings.skill_optimize_max_edits

    reflect = await _complete_json(
        ctx,
        resolved=resolved,
        company_id=company_id,
        system=_REFLECT_SYSTEM.format(max_edits=max_edits),
        user_text=(
            f"CURRENT SKILL FILE:\n{current_text}\n\n"
            f"AUTHORING RUBRIC:\n{rubric_text}\n\n"
            f"EVIDENCE:\n{evidence}"
        ),
        schema=REFLECT_SCHEMA,
        max_tokens=_MAX_REFLECT_TOKENS,
    )
    if reflect is None:
        return None

    new_text = str(reflect.get("revised_skill") or "").strip()
    changes = [str(c).strip() for c in (reflect.get("changes") or []) if str(c).strip()]
    rationale = str(reflect.get("rationale") or "").strip()

    if not changes:
        return None  # the optimizer itself judged no edit was warranted
    if len(changes) > max_edits:
        # Over the learning-rate budget — reject rather than land an unbounded rewrite.
        _log.info(
            "skill_optimizer_over_budget",
            extra={
                "extra_fields": {"skill": skill.name, "changes": len(changes), "cap": max_edits}
            },
        )
        return None
    if not _valid_candidate(new_text, skill_name=skill.name, current_text=current_text):
        return None

    gate = await _complete_json(
        ctx,
        resolved=resolved,
        company_id=company_id,
        system=_GATE_SYSTEM,
        user_text=(
            f"EVIDENCE:\n{evidence}\n\n"
            f"AUTHORING RUBRIC:\n{rubric_text}\n\n"
            f"VERSION A (current):\n{current_text}\n\n"
            f"VERSION B (proposed):\n{new_text}"
        ),
        schema=GATE_SCHEMA,
        max_tokens=_MAX_GATE_TOKENS,
    )
    if gate is None:
        return None
    winner = str(gate.get("winner") or "").strip().upper()
    try:
        margin = int(gate.get("margin", 0))
    except (TypeError, ValueError):
        margin = 0

    # The gate: accept only when the candidate wins by at least the minimum margin.
    if winner != "B" or margin < settings.skill_optimize_gate_min_margin:
        return None
    confidence = "high" if margin >= settings.skill_optimize_gate_auto_margin else "low"

    return SkillProposal(
        skill_name=skill.name,
        title=skill.title,
        repo_path=f"{skills_lib.LIBRARY_REPO_PATH}/{skill.name}.md",
        new_text=new_text,
        changes=changes,
        rationale=rationale or str(gate.get("rationale") or ""),
        gate_margin=margin,
        confidence=confidence,
        signal=signal,
    )


#: Sentinels the implement agent uses to extract the exact file content verbatim.
_BEGIN = "<!-- BEGIN SKILL FILE -->"
_END = "<!-- END SKILL FILE -->"


def build_issue_body(proposal: SkillProposal) -> str:
    """The tracker-issue body: rationale, evidence, and the exact file to write."""
    s = proposal.signal
    changes = "\n".join(f"- {c}" for c in proposal.changes)
    banner = (
        ""
        if proposal.confidence == "high"
        else (
            "> ⚠️ **Low confidence** — the validation gate favored this only slightly. "
            "Please review carefully before merging rather than auto-merging.\n\n"
        )
    )
    return (
        f"{banner}"
        "Automated, validation-gated skill-optimizer proposal.\n\n"
        f"**Skill:** `{proposal.skill_name}` — {proposal.title}\n"
        f"**Recent signal:** {s.success_count}/{s.sample_count} tasks succeeded "
        f"({s.success_rate:.0%}) across {s.sample_count} uses.\n"
        f"**Gate:** the proposed playbook beat the current one by margin "
        f"{proposal.gate_margin}/10 in an independent A/B review.\n\n"
        f"**Why:** {proposal.rationale}\n\n"
        f"**Changes:**\n{changes}\n\n"
        f"**Apply this change:** replace the ENTIRE contents of `{proposal.repo_path}` with "
        f"exactly the text between the two markers below (copy it verbatim, including the "
        f"`---` front matter; do not include the marker lines themselves). This is a "
        f"documentation/playbook edit — no code, tool, or test changes are needed; the "
        f"existing `backend/tests/test_skills_and_mcp.py` suite already validates skill "
        f"well-formedness. Keep the PR scoped to this one file.\n\n"
        f"{_BEGIN}\n{proposal.new_text}\n{_END}\n"
    )


async def file_proposal(
    db: AsyncSession,
    *,
    company_id: uuid.UUID,
    proposal: SkillProposal,
    tracker: IssueTracker,
) -> str | None:
    """File the proposal as a tracker issue and audit it to memory. Returns the URL.

    Title is stable per skill so re-runs de-duplicate (a ``+1`` on the open issue)
    rather than spamming. High-confidence proposals carry the configured labels so
    they enter the auto-merge pipeline; the issue itself always fully specifies the
    change, so the implement step is a verbatim apply. Best-effort: a tracker error
    is logged and swallowed so one bad skill can't break the batch.
    """
    from app.services import memory as memory_svc

    title = f"Skill optimization: improve the '{proposal.skill_name}' playbook"
    body = build_issue_body(proposal)
    labels = list(settings.skill_optimize_labels) if proposal.confidence == "high" else None

    try:
        result = await tracker.report_issue(title=title, body=body, labels=labels)
    except IssueTrackerError:
        # A missing label 422s; retry once without labels so the proposal still lands
        # (triage will label it). Any other tracker error is logged and skipped.
        try:
            result = await tracker.report_issue(title=title, body=body, labels=None)
        except IssueTrackerError:
            _log.exception(
                "skill_optimizer_file_failed",
                extra={"extra_fields": {"skill": proposal.skill_name}},
            )
            return None

    await memory_svc.write(
        db,
        company_id=company_id,
        type=MemoryType.result,
        title=f"Skill optimization proposed: {proposal.skill_name}",
        content=(
            f"Filed {'as' if result.created else 'matched existing'} issue #{result.number} "
            f"({result.url}) to improve the '{proposal.skill_name}' skill "
            f"[{proposal.confidence} confidence, gate margin {proposal.gate_margin}/10].\n\n"
            f"{proposal.rationale}"
        ),
        structured={"kind": "skill_optimization", "skill": proposal.skill_name},
    )
    return result.url


async def run(db: AsyncSession, ctx, *, company_id: uuid.UUID) -> dict:
    """One optimization tick for a company: rank, optimize, and file up to a batch.

    Reads the reward signal, picks the worst-performing skills, and for each runs
    the reflect → gate loop; accepted candidates are filed into the auto-merge
    pipeline. No-ops cleanly when there is no LLM credential or issue tracker.
    """
    resolved = await apikeys.resolve_active_provider(db, company_id=company_id)
    if resolved is None:
        return {"skipped": "no_provider"}

    from app.services.promoter import resolve_issue_tracker

    tracker = await resolve_issue_tracker(db, company_id)

    signals = await signal_svc.collect(
        db, company_id=company_id, window_days=settings.skill_optimize_window_days
    )
    candidates = signal_svc.rank_candidates(
        signals,
        min_samples=settings.skill_optimize_min_samples,
        success_ceiling=settings.skill_optimize_success_ceiling,
    )[: settings.skill_optimize_batch]

    proposed: list[str] = []
    for signal in candidates:
        skill = skills_lib.get_skill(signal.skill_name)
        path = skills_lib.skill_file(signal.skill_name)
        if skill is None or path is None:
            continue
        try:
            current_text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        proposal = await optimize_skill(
            ctx,
            company_id=company_id,
            resolved=resolved,
            skill=skill,
            current_text=current_text,
            signal=signal,
        )
        if proposal is None:
            continue
        if tracker is not None:
            await file_proposal(db, company_id=company_id, proposal=proposal, tracker=tracker)
        proposed.append(proposal.skill_name)

    return {
        "examined": len(candidates),
        "proposed": len(proposed),
        "skills": proposed,
        "tracker": tracker is not None,
    }
