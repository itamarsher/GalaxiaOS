"""Sales tools: lead logging, deal-stage tracking, and follow-up scheduling.

These used to be unsupported stubs — there was no CRM behind them, so they could
only fabricate pipeline, which poisoned the planning loop. They are now backed by
the self-coded CRM (:mod:`app.services.crm`): a lead becomes a real
:class:`~app.models.crm.CrmContact`, a deal update a real
:class:`~app.models.crm.CrmDeal`, and a follow-up a real
:class:`~app.models.crm.CrmActivity`. Nothing is invented; everything persists and
can be read back (see the richer ``crm_*`` tools for search and pipeline views).
"""

from __future__ import annotations

from app.models import Agent, Task
from app.models.enums import CrmActivityKind, CrmDealStage, MetricSource
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.runtime.tools.crm import format_contact, format_deal
from app.services import crm as crm_svc
from app.services import metrics as metrics_svc

#: Allowed deal stages, in pipeline order (the CRM enum is the source of truth).
DEAL_STAGES: tuple[str, ...] = tuple(s.value for s in CrmDealStage)


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="log_lead",
        description="Record a new sales lead in the CRM (name, optional email/company/source/note).",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Lead's full name."},
                "email": {"type": "string"},
                "company": {"type": "string"},
                "source": {"type": "string", "description": "Where the lead came from."},
                "note": {"type": "string"},
            },
            "required": ["name"],
        },
    ),
    ToolSpec(
        name="update_deal",
        description=(
            "Move a deal to a new pipeline stage in the CRM "
            "(new|qualified|proposal|won|lost); records revenue when won."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "lead": {
                    "type": "string",
                    "description": "Lead or deal identifier (name or title).",
                },
                "stage": {
                    "type": "string",
                    "enum": list(DEAL_STAGES),
                },
                "amount_cents": {
                    "type": "integer",
                    "description": "Deal value in cents (recorded as revenue when won).",
                },
                "note": {"type": "string"},
            },
            "required": ["lead", "stage"],
        },
    ),
    ToolSpec(
        name="schedule_followup",
        description="Schedule a follow-up touchpoint with a lead in the CRM.",
        input_schema={
            "type": "object",
            "properties": {
                "lead": {
                    "type": "string",
                    "description": "Lead or deal identifier (name or title).",
                },
                "when": {"type": "string", "description": "When to follow up (free text)."},
                "note": {"type": "string"},
            },
            "required": ["lead", "when"],
        },
    ),
]


async def _log_lead(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    try:
        contact, created = await crm_svc.upsert_contact(
            db,
            company_id=task.company_id,
            name=args["name"],
            email=args.get("email"),
            company_name=args.get("company"),
            source=args.get("source"),
            note=args.get("note"),
        )
    except ValueError as exc:
        return ToolOutcome(observation=str(exc), is_error=True)
    verb = "logged lead" if created else "updated lead"
    return ToolOutcome(observation=f"{verb} {contact.id}: {format_contact(contact)}")


async def _update_deal(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    lead = args["lead"]
    stage_raw = str(args["stage"]).strip().lower()
    try:
        stage = CrmDealStage(stage_raw)
    except ValueError:
        return ToolOutcome(
            observation=f"invalid stage {args['stage']!r}; expected one of {', '.join(DEAL_STAGES)}",
            is_error=True,
        )
    amount_cents = args.get("amount_cents")
    amount_cents = int(amount_cents) if amount_cents is not None else None

    # Link to an existing contact when the lead handle resolves to one.
    contact = await crm_svc.resolve_contact(db, company_id=task.company_id, handle=lead)
    deal, _created = await crm_svc.upsert_deal(
        db,
        company_id=task.company_id,
        title=lead,
        stage=stage,
        amount_cents=amount_cents,
        note=args.get("note"),
        contact_id=contact.id if contact else None,
    )
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
    return ToolOutcome(observation=f"updated deal {deal.id}: {format_deal(deal)}")


async def _schedule_followup(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    lead = args["lead"]
    when = args["when"]
    contact = await crm_svc.resolve_contact(db, company_id=task.company_id, handle=lead)
    body = f"Due: {when}"
    if args.get("note"):
        body += f"\n{args['note']}"
    await crm_svc.log_activity(
        db,
        company_id=task.company_id,
        kind=CrmActivityKind.followup,
        subject=f"Follow up with {lead}",
        body=body,
        contact_id=contact.id if contact else None,
    )
    where = f" (contact {contact.id})" if contact else ""
    return ToolOutcome(observation=f"scheduled follow-up with {lead} at {when}{where}")


HANDLERS = {
    "log_lead": _log_lead,
    "update_deal": _update_deal,
    "schedule_followup": _schedule_followup,
}
