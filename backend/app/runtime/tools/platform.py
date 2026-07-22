"""Platform agent tools: escalation triggers, the demand backlog, and issue filing.

ANY agent that hits a limitation escalates through two trigger tools —
``report_bug`` (something is broken) and ``request_capability`` (I lack a tool).
Rather than immediately waking the Platform agent to file a tracker issue, these
now record the ask in the internal feature-request backlog
(:mod:`app.services.feature_requests`): the request is deduplicated by title and
accrues a vote per (company, user), so the same gap reported by many agents/
companies becomes one entry with a running demand count.

A gated promoter — the Platform agent inside the **platform** company (we dogfood
our own product) — reads that backlog with ``list_feature_requests`` and turns
accrued demand into real tracker issues with ``promote_feature_request``. Both
promoter tools are authorized against the configured operator company, so
only the platform company's agent can file from the cross-company backlog.
Promotion routes through the :mod:`app.integrations.issues` seam
(``report_issue``), which keeps GitHub-side dedup/"+1" voting intact and records an
audit-trail memory. Once the work ships, the platform agent closes the loop with
``deliver_feature_request`` — flipping the entry to ``delivered`` and propagating a
notice to the agents that asked so they resume the blocked work (the scheduled
reconciler does the same automatically when a promoted issue is closed).

``open_issue`` remains available for the Platform agent to file a one-off issue
directly. Filing/promoting are platform/meta actions — no budget charge.
"""

from __future__ import annotations

import uuid

from app.integrations.issues import IssueTrackerError
from app.models import Agent, Task
from app.models.enums import FeatureRequestStatus, MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import feature_requests as fr_svc
from app.services import platform_company, promoter

#: Provider name under which a company's GitHub token is stored (BYOK). Canonical
#: definition lives in the promoter service; re-exported here for callers/tests
#: that reference it via this module.
GITHUB_PROVIDER = promoter.GITHUB_PROVIDER

# ── platform promoter gate ────────────────────────────────────────────────────
# The promoter tools (``list_feature_requests`` / ``promote_feature_request``)
# only work inside the configured operator company (``ABOS_PLATFORM_COMPANY_ID``).
# A tool call from any other tenant's Platform agent is refused. When no operator
# company is configured, no company can promote the shared backlog.


async def _resolve_issue_tracker(db, company_id):
    """The company's tracker (its own token, else the global default), or ``None``.

    Thin delegator to :func:`app.services.promoter.resolve_issue_tracker`, kept as a
    local seam so both ``open_issue`` and ``promote_feature_request`` resolve the
    tracker the same way the scheduled promoter does — and so tests can monkeypatch
    tracker resolution on this module.
    """
    return await promoter.resolve_issue_tracker(db, company_id)


def _is_abos_admin_company(company_id) -> bool:
    """True if the acting company is the configured operator company (promoter gate)."""
    return platform_company.is_platform_company(company_id)


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
                        "The business case: what capability you need and why — the gap it "
                        "would close in your work and the outcome it would unlock. Describe "
                        "the need, not how it should be built in code."
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
            "existing open issue instead of duplicating it. Frame the issue around the "
            "business case and product requirement — the need and the outcome it enables — "
            "rather than a code-level design."
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
        name="deliver_feature_request",
        description=(
            "abos only: mark a backlog entry as delivered/ready once the capability has "
            "been implemented (or the bug fixed). Pass the feature_request_id from "
            "`list_feature_requests`. This flips the entry to 'delivered' and propagates a "
            "notice to every company that requested it — naming the specific agents that "
            "asked — so they resume the work that was blocked. Use this to close the loop by "
            "hand; the scheduled reconciler does the same automatically when a promoted "
            "entry's tracker issue is closed."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "feature_request_id": {
                    "type": "string",
                    "description": "The backlog entry id to mark delivered.",
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

    Attributed to the requesting *agent* (and its task), not a user, so the platform
    can see which agent hit the gap and route the delivery back to it. Deduplicated
    by title with a running demand count.
    """
    outcome = await fr_svc.record_request(
        db,
        kind=kind,
        title=title,
        details=details,
        company_id=task.company_id,
        user_id=None,
        agent_id=task.agent_id,
        task_id=task.id,
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
    if not _is_abos_admin_company(task.company_id):
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
        companies = sorted({a.company_name for a in attribution})
        agents = sorted({a.agent_name for a in attribution if a.agent_name})
        company_note = ", ".join(companies[:3]) + ("…" if len(companies) > 3 else "")
        agent_note = (
            "; agents: " + ", ".join(agents[:3]) + ("…" if len(agents) > 3 else "")
            if agents
            else ""
        )
        lines.append(
            f"- [{fr.kind.value}] {fr.title!r} — {fr.vote_count} vote(s) "
            f"from {len(companies)} compan{'y' if len(companies) == 1 else 'ies'} "
            f"({company_note}{agent_note})\n  id: {fr.id}"
        )
    return ToolOutcome(
        observation=(
            f"{len(entries)} open backlog entr{'y' if len(entries) == 1 else 'ies'} "
            "(most-demanded first):\n" + "\n".join(lines)
        )
    )


async def _promote_feature_request(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if not _is_abos_admin_company(task.company_id):
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
    if fr.status is not FeatureRequestStatus.open:
        return ToolOutcome(
            observation=(
                f"{fr.title!r} was already {fr.status.value} "
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

    # Shared with the scheduled promoter so interactive and cron promotion behave
    # identically (same issue body, labels, mark-promoted, and memory audit).
    try:
        result = await promoter.promote_request(
            db, fr=fr, tracker=tracker, company_id=task.company_id, source_task_id=task.id
        )
    except IssueTrackerError as exc:
        return ToolOutcome(observation=f"could not file issue: {exc}", is_error=True)

    verb = "filed" if result.created else "matched an existing"
    return ToolOutcome(
        observation=(
            f"Promoted {fr.title!r} (demand {fr.vote_count}); {verb} issue #{result.number} "
            f"via {result.provider} ({result.url}). GitHub demand now {result.demand}."
        )
    )


async def _deliver_feature_request(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if not _is_abos_admin_company(task.company_id):
        return ToolOutcome(
            observation=(
                "Not authorized: only the abos company can mark backlog entries delivered."
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
    if fr.status is FeatureRequestStatus.delivered:
        return ToolOutcome(observation=f"{fr.title!r} was already marked delivered.")

    notified = await promoter.deliver_request(db, fr)
    return ToolOutcome(
        observation=(
            f"Marked {fr.title!r} delivered and notified {notified} requesting "
            f"compan{'y' if notified == 1 else 'ies'} — the agents that asked will resume "
            "the work that was blocked."
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
    "deliver_feature_request": _deliver_feature_request,
    "open_issue": _open_issue,
}
