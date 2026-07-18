"""CRM tools: the agents' interface to the self-coded, persistent CRM.

Unlike the legacy sales stubs (which had nothing behind them and so report the
capability as unsupported), these tools are backed by real tenant-scoped tables
via :mod:`app.services.crm` — contacts, deals, and activities actually persist
and can be read back. That makes them safe to act on: an agent reads its real
pipeline instead of inventing one.

Capabilities exposed:
- ``crm_save_contact`` / ``crm_find_contacts`` — manage and search people/accounts.
- ``crm_save_deal`` / ``crm_list_deals`` — manage the opportunity pipeline (won
  deals also record a real ``revenue`` metric signal).
- ``crm_log_activity`` — log an interaction or schedule a follow-up.
- ``crm_contact_timeline`` — pull a contact with their deals and recent activity.

Agents may reference a contact by id, email, or name, and a deal by id or title;
the service resolves the handle. All writes are deterministic and free (no LLM,
no external charge, no network).
"""

from __future__ import annotations

from app.models import Agent, Task
from app.models.enums import (
    CrmActivityKind,
    CrmContactStatus,
    CrmDealStage,
    MetricSource,
)
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import crm as crm_svc
from app.services import data_policy
from app.services import metrics as metrics_svc

CONTACT_STATUSES: tuple[str, ...] = tuple(s.value for s in CrmContactStatus)
DEAL_STAGES: tuple[str, ...] = tuple(s.value for s in CrmDealStage)
ACTIVITY_KINDS: tuple[str, ...] = tuple(k.value for k in CrmActivityKind)

# The CRM is customer data. Reading it back is gated on the ``customers`` label
# (data segmentation, RFC 0001); the CEO bypasses. Writing/logging is unaffected —
# the policy governs what stored data is *provided to* an agent, not what it records.
_CRM_LABELS = ["customers"]


def _crm_read_denied(agent: Agent) -> ToolOutcome | None:
    """A denial outcome when ``agent`` isn't cleared to read customer data, else None."""
    if data_policy.agent_can_access(agent, _CRM_LABELS):
        return None
    return ToolOutcome(
        observation=(
            "You don't have access to customer data (the CRM). Ask the founder to "
            "grant your agent the 'customers' data label if you need it."
        ),
        is_error=True,
    )


def _dollars(cents: int | None) -> str:
    return f"${(int(cents or 0)) / 100:,.2f}"


def _enum(value, enum_cls, label: str):
    """Coerce ``value`` to an ``enum_cls`` member, raising a clear ValueError."""
    normalized = str(value).strip().lower()
    try:
        return enum_cls(normalized)
    except ValueError:
        allowed = ", ".join(m.value for m in enum_cls)
        raise ValueError(f"invalid {label} {value!r}; expected one of {allowed}") from None


def format_contact(contact) -> str:
    """One-line, deterministic summary of a contact."""
    parts = [contact.name]
    for value in (contact.title, contact.company_name):
        if value:
            parts.append(value)
    head = " — ".join(parts)
    extra = [f"status={contact.status.value}"]
    if contact.email:
        extra.append(contact.email)
    if contact.source:
        extra.append(f"source={contact.source}")
    return f"{head} [{', '.join(extra)}]"


def format_deal(deal) -> str:
    """One-line, deterministic summary of a deal."""
    line = f"{deal.title} -> {deal.stage.value}"
    if deal.amount_cents is not None:
        line += f" ({_dollars(deal.amount_cents)})"
    return line


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="crm_save_contact",
        description=(
            "Create or update a CRM contact (a person/account). Matches an existing "
            "contact by id or email so re-saving updates rather than duplicates. "
            "Only the fields you pass are written."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "contact_id": {
                    "type": "string",
                    "description": "Existing contact id to update (optional).",
                },
                "name": {"type": "string", "description": "Full name."},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "company": {"type": "string", "description": "The contact's organisation."},
                "title": {"type": "string", "description": "Job title / role."},
                "source": {"type": "string", "description": "Where the contact came from."},
                "status": {"type": "string", "enum": list(CONTACT_STATUSES)},
                "note": {"type": "string"},
            },
        },
    ),
    ToolSpec(
        name="crm_find_contacts",
        description=(
            "Search the CRM for contacts by free text (name/email/company) and/or "
            "lifecycle status. Returns the matching contacts."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search."},
                "status": {"type": "string", "enum": list(CONTACT_STATUSES)},
                "limit": {"type": "integer", "description": "Max results (default 20)."},
            },
        },
    ),
    ToolSpec(
        name="crm_save_deal",
        description=(
            "Create or advance a deal in the pipeline "
            "(stage: new|qualified|proposal|won|lost). Matches an existing deal by id "
            "or title. Records a real revenue metric when a deal is marked won with an "
            "amount. Optionally link the deal to a contact (by id, email, or name)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "deal_id": {
                    "type": "string",
                    "description": "Existing deal id to update (optional).",
                },
                "title": {"type": "string", "description": "Deal name (required for new deals)."},
                "stage": {"type": "string", "enum": list(DEAL_STAGES)},
                "amount_cents": {
                    "type": "integer",
                    "description": "Deal value in cents (recorded as revenue when won).",
                },
                "contact": {
                    "type": "string",
                    "description": "Contact to link, by id / email / name (optional).",
                },
                "note": {"type": "string"},
            },
        },
    ),
    ToolSpec(
        name="crm_list_deals",
        description=(
            "List deals (optionally filtered by stage) and a pipeline summary "
            "(count and total value per stage)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "stage": {"type": "string", "enum": list(DEAL_STAGES)},
                "limit": {"type": "integer", "description": "Max deals listed (default 50)."},
            },
        },
    ),
    ToolSpec(
        name="crm_log_activity",
        description=(
            "Log a CRM interaction (note/call/email/meeting) or schedule a touchpoint "
            "(task/follow-up). Optionally tie it to a contact and/or deal."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(ACTIVITY_KINDS)},
                "subject": {"type": "string", "description": "Short summary."},
                "body": {"type": "string", "description": "Details / what was said."},
                "contact": {
                    "type": "string",
                    "description": "Contact this relates to, by id / email / name (optional).",
                },
                "deal": {
                    "type": "string",
                    "description": "Deal this relates to, by id / title (optional).",
                },
                "when": {
                    "type": "string",
                    "description": "For a task/follow-up: when it's due (free text).",
                },
            },
            "required": ["kind"],
        },
    ),
    ToolSpec(
        name="crm_contact_timeline",
        description=(
            "Pull one contact with their linked deals and recent activity — the full "
            "relationship view. Identify the contact by id, email, or name."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "contact": {
                    "type": "string",
                    "description": "Contact to view, by id / email / name.",
                },
            },
            "required": ["contact"],
        },
    ),
]


async def _crm_save_contact(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    status = None
    if args.get("status"):
        try:
            status = _enum(args["status"], CrmContactStatus, "status")
        except ValueError as exc:
            return ToolOutcome(observation=str(exc), is_error=True)
    try:
        contact, created = await crm_svc.upsert_contact(
            db,
            company_id=task.company_id,
            contact_id=args.get("contact_id"),
            name=args.get("name"),
            email=args.get("email"),
            phone=args.get("phone"),
            company_name=args.get("company"),
            title=args.get("title"),
            source=args.get("source"),
            status=status,
            note=args.get("note"),
        )
    except ValueError as exc:
        return ToolOutcome(observation=str(exc), is_error=True)
    verb = "created" if created else "updated"
    return ToolOutcome(observation=f"{verb} contact {contact.id}: {format_contact(contact)}")


async def _crm_find_contacts(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (denied := _crm_read_denied(agent)) is not None:
        return denied
    status = None
    if args.get("status"):
        try:
            status = _enum(args["status"], CrmContactStatus, "status")
        except ValueError as exc:
            return ToolOutcome(observation=str(exc), is_error=True)
    limit = int(args.get("limit") or 20)
    contacts = await crm_svc.find_contacts(
        db, company_id=task.company_id, query=args.get("query"), status=status, limit=limit
    )
    if not contacts:
        return ToolOutcome(observation="No matching contacts in the CRM.")
    lines = [f"- {c.id}: {format_contact(c)}" for c in contacts]
    return ToolOutcome(observation=f"{len(contacts)} contact(s):\n" + "\n".join(lines))


async def _crm_save_deal(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    stage = None
    if args.get("stage"):
        try:
            stage = _enum(args["stage"], CrmDealStage, "stage")
        except ValueError as exc:
            return ToolOutcome(observation=str(exc), is_error=True)

    contact_id = None
    if args.get("contact"):
        contact = await crm_svc.resolve_contact(
            db, company_id=task.company_id, handle=args["contact"]
        )
        if contact is None:
            return ToolOutcome(
                observation=f"no contact matches {args['contact']!r}; create it first with crm_save_contact.",
                is_error=True,
            )
        contact_id = contact.id

    amount_cents = args.get("amount_cents")
    amount_cents = int(amount_cents) if amount_cents is not None else None
    try:
        deal, created = await crm_svc.upsert_deal(
            db,
            company_id=task.company_id,
            deal_id=args.get("deal_id"),
            title=args.get("title"),
            stage=stage,
            amount_cents=amount_cents,
            note=args.get("note"),
            contact_id=contact_id,
        )
    except ValueError as exc:
        return ToolOutcome(observation=str(exc), is_error=True)

    # A won deal with a value is a real, recorded outcome — feed it into the
    # metrics loop the same way the finance tools record revenue.
    if deal.stage == CrmDealStage.won and deal.amount_cents:
        await metrics_svc.record_signal(
            db,
            company_id=task.company_id,
            name="revenue",
            value=deal.amount_cents / 100,
            unit="USD",
            source=MetricSource.agent,
            note=f"deal won: {deal.title}",
        )
    verb = "created" if created else "updated"
    return ToolOutcome(observation=f"{verb} deal {deal.id}: {format_deal(deal)}")


async def _crm_list_deals(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (denied := _crm_read_denied(agent)) is not None:
        return denied
    stage = None
    if args.get("stage"):
        try:
            stage = _enum(args["stage"], CrmDealStage, "stage")
        except ValueError as exc:
            return ToolOutcome(observation=str(exc), is_error=True)
    limit = int(args.get("limit") or 50)
    deals = await crm_svc.list_deals(db, company_id=task.company_id, stage=stage, limit=limit)
    summary = await crm_svc.pipeline_summary(db, company_id=task.company_id)
    summary_lines = [
        f"- {s.value}: {summary[s]['count']} deal(s), {_dollars(summary[s]['value_cents'])}"
        for s in CrmDealStage
    ]
    body = "Pipeline:\n" + "\n".join(summary_lines)
    if deals:
        deal_lines = [f"- {d.id}: {format_deal(d)}" for d in deals]
        body += f"\n\n{len(deals)} deal(s):\n" + "\n".join(deal_lines)
    return ToolOutcome(observation=body)


async def _crm_log_activity(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    try:
        kind = _enum(args["kind"], CrmActivityKind, "kind")
    except ValueError as exc:
        return ToolOutcome(observation=str(exc), is_error=True)

    contact_id = None
    if args.get("contact"):
        contact = await crm_svc.resolve_contact(
            db, company_id=task.company_id, handle=args["contact"]
        )
        if contact is None:
            return ToolOutcome(
                observation=f"no contact matches {args['contact']!r}.", is_error=True
            )
        contact_id = contact.id

    deal_id = None
    if args.get("deal"):
        deal = await crm_svc.resolve_deal(db, company_id=task.company_id, handle=args["deal"])
        if deal is None:
            return ToolOutcome(observation=f"no deal matches {args['deal']!r}.", is_error=True)
        deal_id = deal.id

    # ``when`` is free text (no calendar to parse it into a real time), so keep it
    # in the body rather than fabricating a precise due_at.
    body = args.get("body")
    when = args.get("when")
    if when:
        body = f"Due: {when}" + (f"\n{body}" if body else "")

    activity = await crm_svc.log_activity(
        db,
        company_id=task.company_id,
        kind=kind,
        subject=args.get("subject"),
        body=body,
        contact_id=contact_id,
        deal_id=deal_id,
    )
    target = ""
    if contact_id:
        target += " for contact"
    if deal_id:
        target += " on deal"
    return ToolOutcome(observation=f"logged {kind.value} activity {activity.id}{target}".rstrip())


async def _crm_contact_timeline(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    if (denied := _crm_read_denied(agent)) is not None:
        return denied
    contact = await crm_svc.resolve_contact(db, company_id=task.company_id, handle=args["contact"])
    if contact is None:
        return ToolOutcome(observation=f"no contact matches {args['contact']!r}.", is_error=True)
    deals = await crm_svc.list_deals(db, company_id=task.company_id)
    contact_deals = [d for d in deals if d.contact_id == contact.id]
    activities = await crm_svc.list_activities(
        db, company_id=task.company_id, contact_id=contact.id, limit=20
    )

    lines = [format_contact(contact), f"id={contact.id}"]
    if contact.note:
        lines.append(f"note: {contact.note}")
    if contact_deals:
        lines.append("\nDeals:")
        lines += [f"- {format_deal(d)}" for d in contact_deals]
    if activities:
        lines.append("\nActivity (most recent first):")
        for a in activities:
            subj = a.subject or (a.body[:80] if a.body else "")
            lines.append(f"- {a.kind.value}: {subj}".rstrip(": "))
    return ToolOutcome(observation="\n".join(lines))


HANDLERS = {
    "crm_save_contact": _crm_save_contact,
    "crm_find_contacts": _crm_find_contacts,
    "crm_save_deal": _crm_save_deal,
    "crm_list_deals": _crm_list_deals,
    "crm_log_activity": _crm_log_activity,
    "crm_contact_timeline": _crm_contact_timeline,
}
