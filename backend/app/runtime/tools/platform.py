"""Platform agent tools: escalation triggers, the demand backlog, and issue filing.

ANY agent that hits a limitation escalates through two trigger tools —
``report_bug`` (something is broken) and ``request_capability`` (I lack a tool).
Rather than immediately waking the Platform agent to file a tracker issue, these
now record the ask in the internal feature-request backlog
(:mod:`app.services.feature_requests`): the request is deduplicated by title and
accrues a vote per (company, user), so the same gap reported by many agents/
companies becomes one entry with a running demand count.

A gated promoter — the Platform agent inside the **abos** company (we dogfood our
own product) — reads that backlog with ``list_feature_requests`` and turns
accrued demand into real tracker issues with ``promote_feature_request``. Both
promoter tools are authorized against a hardcoded abos admin user id, so only the
abos company's agent can file from the cross-company backlog. Promotion routes
through the :mod:`app.integrations.issues` seam (``report_issue``), which keeps
GitHub-side dedup/"+1" voting intact and records an audit-trail memory.

``open_issue`` remains available for the Platform agent to file a one-off issue
directly. Filing/promoting are platform/meta actions — no budget charge.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.config import settings
from app.integrations.issues import (
    GitHubIssueTracker,
    IssueTrackerError,
    get_issue_tracker,
)
from app.models import Agent, Membership, Task
from app.models.enums import FeatureRequestKind, FeatureRequestStatus, MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import apikeys
from app.services import feature_requests as fr_svc

#: Provider name under which a company's GitHub token is stored (BYOK).
GITHUB_PROVIDER = "github"

# ── abos promoter gate ────────────────────────────────────────────────────────
# The promoter tools (``list_feature_requests`` / ``promote_feature_request``)
# only work inside the abos company — the one whose founder is this user. We
# authorize by checking that this user is a member of the acting company, so a
# tool call from any other tenant's Platform agent is refused.
#
# IMPORTANT: replace this placeholder with the real abos founder's user id before
# the promoter can be used. An empty/placeholder value matches no membership, so
# the gate safely denies everyone until it is set.
ABOS_FEATURE_ADMIN_USER_ID = "00000000-0000-0000-0000-000000000000"

#: Maps a backlog kind to the tracker label used when filing.
_KIND_LABEL = {
    FeatureRequestKind.bug: "bug",
    FeatureRequestKind.capability: "enhancement",
}


async def _resolve_issue_tracker(db, company_id):
    """Use the company's own GitHub token if it set one, else the global default.

    A founder can attach a GitHub token per company (in onboarding or Settings);
    when present we file real issues against ``settings.github_repo``. Without one
    we fall back to the configured default tracker, which is ``None`` unless the
    deployment set a global GitHub token — there is no simulated tracker.
    """
    token = await apikeys.get_plaintext_key(
        db, company_id=company_id, provider=GITHUB_PROVIDER
    )
    if token:
        return GitHubIssueTracker(token, repo=settings.github_repo)
    return get_issue_tracker()


async def _is_abos_admin_company(db, company_id) -> bool:
    """True if the acting company is the abos admin company (gate for the promoter)."""
    try:
        admin_id = uuid.UUID(str(ABOS_FEATURE_ADMIN_USER_ID))
    except (ValueError, TypeError):
        return False
    membership_id = await db.scalar(
        select(Membership.id).where(
            Membership.user_id == admin_id, Membership.company_id == company_id
        )
    )
    return membership_id is not None


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="report_bug",
        description=(
            "Report a bug or broken behaviour. Use this when you hit something that is "
            "clearly malfunctioning (a tool errors, a result is wrong) rather than "
            "stalling your own task. It is logged to the shared feature-request backlog "
            "(deduplicated by title, with a running demand count); the abos team reviews "
            "the backlog and files tracker issues. You can carry on with your task."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short summary of the bug."},
                "details": {
                    "type": "string",
                    "description": (
                        "What you were doing, what happened, and what you expected — "
                        "enough for someone to investigate."
                    ),
                },
            },
            "required": ["title", "details"],
        },
    ),
    ToolSpec(
        name="request_capability",
        description=(
            "Request a new capability or tool. Use this when you lack a tool you need to "
            "do your job, instead of giving up on the task. It is logged to the shared "
            "feature-request backlog (deduplicated by title, with a running demand count "
            "across all companies); the abos team reviews demand and files feature-request "
            "issues. You can carry on with your task."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short summary of the capability."},
                "details": {
                    "type": "string",
                    "description": (
                        "What capability you need and why — the gap it would close in "
                        "your work."
                    ),
                },
            },
            "required": ["title", "details"],
        },
    ),
    ToolSpec(
        name="list_feature_requests",
        description=(
            "abos only: list the open feature-request backlog (deduped asks with their "
            "demand/vote counts and which companies requested them), most-demanded first. "
            "Use this to decide what to promote into a tracker issue. Optionally filter by "
            "kind ('bug' or 'capability') and a minimum vote threshold."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["bug", "capability"],
                    "description": "Optional: only this kind.",
                },
                "min_votes": {
                    "type": "integer",
                    "description": "Optional: only entries with at least this many votes.",
                },
                "limit": {"type": "integer", "description": "Optional: max entries (default 25)."},
            },
        },
    ),
    ToolSpec(
        name="promote_feature_request",
        description=(
            "abos only: file a backlog entry as a real tracker issue and mark it promoted. "
            "Pass the feature_request_id from `list_feature_requests`. The issue body "
            "summarizes demand and which companies/users asked. Routes through the tracker "
            "(GitHub when credentials are set), which still dedupes by title and '+1's an "
            "existing open issue instead of duplicating it. Investigate the relevant code "
            "with `list_repo_files` / `read_repo_file` first if useful."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "feature_request_id": {
                    "type": "string",
                    "description": "The backlog entry id to promote.",
                },
            },
            "required": ["feature_request_id"],
        },
    ),
    ToolSpec(
        name="open_issue",
        description=(
            "Platform agent: file a tracker issue (bug or feature request) directly. It "
            "first checks for an existing open issue with the SAME title and, if found, adds "
            "a '+1' comment instead of opening a duplicate — so the comment count tracks how "
            "many need it. Routes through the configured tracker (GitHub when credentials are "
            "set; otherwise recorded and counted in company memory) and records the outcome "
            "for the audit trail. Reuse a consistent title so duplicates collapse into one "
            "counted request."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {
                    "type": "string",
                    "description": "The issue body, in Markdown.",
                },
                "labels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional labels, e.g. ['bug'] or ['enhancement'].",
                },
            },
            "required": ["title", "body"],
        },
    ),
]


# ── escalation triggers → demand backlog ──────────────────────────────────────


async def _record_request(
    db, *, task: Task, kind: str, title: str, details: str
) -> ToolOutcome:
    """Record an agent-initiated bug/capability request in the demand backlog.

    Agent context has no specific user, so the vote is attributed to the company
    (``user_id=None``). Deduplicated by title with a running demand count.
    """
    outcome = await fr_svc.record_request(
        db,
        kind=kind,
        title=title,
        details=details,
        company_id=task.company_id,
        user_id=None,
    )
    if outcome is None:
        return ToolOutcome(
            observation="Could not record the request (empty title?). Carry on with your task.",
            is_error=True,
        )

    noun = "capability request" if kind == "capability" else "bug report"
    if outcome.is_new_feature:
        detail = f"opened a new backlog entry (demand: {outcome.votes})"
    elif outcome.is_new_vote:
        detail = f"added your company's vote to an existing entry (demand now {outcome.votes})"
    else:
        detail = f"your company had already requested this (demand stays {outcome.votes})"
    return ToolOutcome(
        observation=(
            f"Logged a {noun} to the feature-request backlog: {title[:80]!r} — {detail}. "
            "The abos team reviews demand and files tracker issues; carry on with your task."
        )
    )


async def _report_bug(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return await _record_request(
        db,
        task=task,
        kind="bug",
        title=str(args["title"]).strip(),
        details=str(args["details"]).strip(),
    )


async def _request_capability(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return await _record_request(
        db,
        task=task,
        kind="capability",
        title=str(args["title"]).strip(),
        details=str(args["details"]).strip(),
    )


# ── abos promoter: read the backlog and file issues ───────────────────────────


async def _list_feature_requests(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if not await _is_abos_admin_company(db, task.company_id):
        return ToolOutcome(
            observation=(
                "Not authorized: the feature-request backlog can only be reviewed from the "
                "abos company."
            ),
            is_error=True,
        )

    kind = fr_svc.coerce_kind(args["kind"]) if args.get("kind") else None
    min_votes = int(args.get("min_votes") or 1)
    limit = int(args.get("limit") or 25)
    entries = await fr_svc.list_open(db, kind=kind, min_votes=min_votes, limit=limit)
    if not entries:
        return ToolOutcome(observation="The open feature-request backlog is empty.")

    lines = []
    for fr in entries:
        attribution = await fr_svc.load_attribution(db, fr.id)
        companies = sorted({name for name, _e, _d in attribution})
        company_note = ", ".join(companies[:3]) + ("…" if len(companies) > 3 else "")
        lines.append(
            f"- [{fr.kind.value}] {fr.title!r} — {fr.vote_count} vote(s) "
            f"from {len(companies)} compan{'y' if len(companies) == 1 else 'ies'} "
            f"({company_note})\n  id: {fr.id}"
        )
    return ToolOutcome(
        observation=(
            f"{len(entries)} open backlog entr{'y' if len(entries) == 1 else 'ies'} "
            "(most-demanded first):\n" + "\n".join(lines)
        )
    )


async def _promote_feature_request(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.services import memory as memory_svc

    if not await _is_abos_admin_company(db, task.company_id):
        return ToolOutcome(
            observation=(
                "Not authorized: only the abos company can promote backlog entries into "
                "tracker issues."
            ),
            is_error=True,
        )

    try:
        fr_id = uuid.UUID(str(args["feature_request_id"]).strip())
    except (ValueError, TypeError):
        return ToolOutcome(observation="Invalid feature_request_id.", is_error=True)

    fr = await fr_svc.get(db, fr_id)
    if fr is None:
        return ToolOutcome(observation="No backlog entry with that id.", is_error=True)
    if fr.status is FeatureRequestStatus.promoted:
        return ToolOutcome(
            observation=(
                f"{fr.title!r} was already promoted "
                f"(issue #{fr.github_issue_number}, {fr.github_issue_url})."
            )
        )

    tracker = await _resolve_issue_tracker(db, task.company_id)
    if tracker is None:
        return ToolOutcome(
            observation=(
                "No issue tracker is connected, so this can't be filed yet. Connect a GitHub "
                "token (Settings or ABOS_GITHUB_TOKEN) and try again."
            ),
            is_error=True,
        )

    body = await fr_svc.build_issue_body(db, fr)
    label = _KIND_LABEL.get(fr.kind, "enhancement")
    try:
        result = await tracker.report_issue(title=fr.title, body=body, labels=[label])
    except IssueTrackerError as exc:
        return ToolOutcome(observation=f"could not file issue: {exc}", is_error=True)

    await fr_svc.mark_promoted(
        db, fr, issue_number=result.number, issue_url=result.url
    )
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Feature request promoted: {fr.title[:80]}",
        content=(
            f"Backlog entry {fr.id} ({fr.vote_count} vote(s)) "
            f"{'filed as' if result.created else 'matched existing'} issue "
            f"#{result.number} via {result.provider}.\nURL: {result.url}\n\n{body}"
        ),
        source_task_id=task.id,
    )

    verb = "filed" if result.created else "matched an existing"
    return ToolOutcome(
        observation=(
            f"Promoted {fr.title!r} (demand {fr.vote_count}); {verb} issue #{result.number} "
            f"via {result.provider} ({result.url}). GitHub demand now {result.demand}."
        )
    )


# ── direct issue filing (open_issue) ──────────────────────────────────────────


async def _record_request_internally(
    db, task: Task, *, title: str, body: str, label_part: str
) -> ToolOutcome:
    """Track a bug/capability request in company memory when no tracker is wired.

    Deduplicates by title: a repeat of an existing request bumps a counter on the
    same entry (so we can see how many agents need it) instead of stacking duplicate
    memories.
    """
    from app.services import memory as memory_svc

    mem_title = f"Platform request: {title[:80]}"
    existing = await memory_svc.find_latest_by_title(
        db, company_id=task.company_id, title=mem_title
    )
    if existing is not None:
        structured = dict(existing.structured or {})
        count = int(structured.get("request_count") or 1) + 1
        structured["request_count"] = count
        existing.structured = structured
        existing.content = (
            f"Recorded internally{label_part} — no external issue tracker is connected. "
            f"Demand so far: {count} request(s) from agents.\n\n{body}"
        )
        await db.flush()
        return ToolOutcome(
            observation=(
                f"This was already recorded internally; counted another request for it "
                f"(demand now {count}) instead of duplicating it. Connect a GitHub token "
                "in Settings to file it in a real tracker."
            )
        )

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=mem_title,
        content=(
            f"Recorded internally{label_part} — no external issue tracker is connected, so "
            "this was saved to company memory rather than filed in a tracker. Demand so "
            f"far: 1 request.\n\n{body}"
        ),
        source_task_id=task.id,
        structured={"request_count": 1, "kind": "platform_request"},
    )
    return ToolOutcome(
        observation=(
            f"No external issue tracker is connected, so {title[:80]!r} was recorded "
            "internally to company memory (demand: 1). To file it in a real tracker, "
            "connect a GitHub token in Settings."
        )
    )


async def _open_issue(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    from app.services import memory as memory_svc

    title = str(args["title"]).strip()
    body = str(args["body"]).strip()
    labels = [str(x) for x in (args.get("labels") or []) if str(x).strip()]
    label_part = f" [{', '.join(labels)}]" if labels else ""

    tracker = await _resolve_issue_tracker(db, task.company_id)

    # No external tracker configured: track the request in the company's own memory
    # (deduped + counted) so the escalation loop still produces a durable artifact.
    if tracker is None:
        return await _record_request_internally(
            db, task, title=title, body=body, label_part=label_part
        )

    try:
        result = await tracker.report_issue(title=title, body=body, labels=labels)
    except IssueTrackerError as exc:
        return ToolOutcome(observation=f"could not open issue: {exc}", is_error=True)

    # Audit trail: record what happened to company memory.
    if result.created:
        await memory_svc.write(
            db,
            company_id=task.company_id,
            type=MemoryType.result,
            title=f"Issue filed: {title[:80]}",
            content=(
                f"Tracker issue #{result.number} opened via {result.provider}{label_part}.\n"
                f"URL: {result.url}\n\n{body}"
            ),
            source_task_id=task.id,
        )
        return ToolOutcome(
            observation=(
                f"opened issue #{result.number} via {result.provider} "
                f"(id {result.id}, {result.url})"
            )
        )

    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Issue +1'd: {title[:80]}",
        content=(
            f"A duplicate of existing tracker issue #{result.number} "
            f"({result.provider}){label_part}; added a +1 comment instead of filing a new "
            f"one. Demand so far: {result.demand} request(s).\nURL: {result.url}"
        ),
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=(
            f"found existing issue #{result.number} for this and added a +1 comment instead "
            f"of opening a duplicate — demand is now {result.demand} request(s) ({result.url})"
        )
    )


HANDLERS = {
    "report_bug": _report_bug,
    "request_capability": _request_capability,
    "list_feature_requests": _list_feature_requests,
    "promote_feature_request": _promote_feature_request,
    "open_issue": _open_issue,
}
