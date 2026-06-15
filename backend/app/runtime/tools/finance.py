"""Finance tools: budget/metrics visibility, transaction recording, invoicing.

Area-specific tools for the finance function. Everything here is deterministic
and simulated — there is no network, no new config, and no real-money charge.
``read_financials`` is the finance agent's zero-cost window into the real
numbers (the monthly :class:`Budget` plus recent metric signals);
``record_transaction`` and ``generate_invoice`` persist outcomes as metric
signals and institutional memory. Generating an invoice bills a customer, so it
deliberately does *not* charge the company budget.
"""

from __future__ import annotations

from sqlalchemy import select

from app.integrations.invoicing import get_invoicer
from app.models import Agent, Budget, Task
from app.models.enums import BudgetPeriod, MemoryType, MetricSource
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import memory as memory_svc
from app.services import metrics as metrics_svc

#: Allowed transaction kinds (also the metric signal name recorded).
TRANSACTION_KINDS: tuple[str, ...] = ("revenue", "expense")


def _dollars(cents: int | None) -> str:
    """Format integer cents as a ``$X.XX`` dollar string (``$0.00`` for ``None``)."""
    return f"${(int(cents or 0)) / 100:,.2f}"


def validate_kind(kind: str) -> str:
    """Return a normalized transaction kind or raise ``ValueError`` if unknown."""
    normalized = str(kind).strip().lower()
    if normalized not in TRANSACTION_KINDS:
        raise ValueError(
            f"invalid kind {kind!r}; expected one of {', '.join(TRANSACTION_KINDS)}"
        )
    return normalized


def format_budget_summary(budget: Budget | None) -> str:
    """Compact, deterministic rendering of the monthly budget (handles ``None``)."""
    if budget is None:
        return "Monthly budget: not configured."
    remaining = int(budget.limit_cents) - int(budget.spent_cents) - int(budget.reserved_cents)
    return (
        "Monthly budget — "
        f"limit {_dollars(budget.limit_cents)}, "
        f"spent {_dollars(budget.spent_cents)}, "
        f"reserved {_dollars(budget.reserved_cents)}, "
        f"remaining {_dollars(remaining)}."
    )


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="read_financials",
        description=(
            "Read the company's real financial position: the monthly budget "
            "(limit/spent/reserved/remaining) plus recent business metrics. Zero cost."
        ),
        input_schema={"type": "object", "properties": {}},
    ),
    ToolSpec(
        name="record_transaction",
        description=(
            "Record an observed financial transaction (revenue or expense) as a "
            "metric signal and institutional memory. Does not move the budget."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": list(TRANSACTION_KINDS)},
                "amount_cents": {
                    "type": "integer",
                    "description": "Transaction amount in cents.",
                },
                "category": {"type": "string", "description": "Optional accounting category."},
                "note": {"type": "string"},
            },
            "required": ["kind", "amount_cents"],
        },
    ),
    ToolSpec(
        name="generate_invoice",
        description=(
            "Generate a deterministic customer invoice (no network). Logs the "
            "invoice and records it as an 'invoiced' metric. Does not charge the budget."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "customer": {"type": "string", "description": "Customer being billed."},
                "amount_cents": {
                    "type": "integer",
                    "description": "Invoice amount in cents.",
                },
                "description": {"type": "string", "description": "What the invoice is for."},
            },
            "required": ["customer", "amount_cents"],
        },
    ),
]


async def _read_financials(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    budget = await db.scalar(
        select(Budget).where(
            Budget.company_id == task.company_id, Budget.period == BudgetPeriod.monthly
        )
    )
    signals = await metrics_svc.latest_signals(db, company_id=task.company_id, limit=8)
    observation = f"{format_budget_summary(budget)}\n\n{metrics_svc.summarize_for_prompt(signals)}"
    return ToolOutcome(observation=observation)


async def _record_transaction(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    try:
        kind = validate_kind(args["kind"])
    except ValueError as exc:
        return ToolOutcome(observation=str(exc), is_error=True)
    amount_cents = int(args["amount_cents"])
    category = args.get("category")
    note = args.get("note")

    detail = f"{kind} {_dollars(amount_cents)}"
    if category:
        detail += f" [{category}]"
    signal_note = note or (f"category: {category}" if category else None)

    await metrics_svc.record_signal(
        db,
        company_id=task.company_id,
        name=kind,
        value=amount_cents / 100,
        unit="USD",
        source=MetricSource.agent,
        note=signal_note,
    )
    content = detail if not note else f"{detail}\n{note}"
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Transaction: {detail}",
        content=content,
        source_task_id=task.id,
    )
    return ToolOutcome(observation=f"recorded {detail}")


async def _generate_invoice(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    customer = args["customer"]
    amount_cents = int(args["amount_cents"])
    description = args.get("description")

    invoice = get_invoicer().generate(
        company_id=str(task.company_id),
        customer=customer,
        amount_cents=amount_cents,
        description=description,
    )

    content = f"Invoice {invoice.invoice_id} to {customer} for {_dollars(amount_cents)}."
    if description:
        content += f" For: {description}"
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.decision,
        title=f"Invoice {invoice.invoice_id} -> {customer}",
        content=content,
        source_task_id=task.id,
    )
    await metrics_svc.record_signal(
        db,
        company_id=task.company_id,
        name="invoiced",
        value=amount_cents / 100,
        unit="USD",
        source=MetricSource.agent,
        note=f"invoice {invoice.invoice_id} -> {customer}",
    )
    return ToolOutcome(
        observation=f"generated invoice {invoice.invoice_id} -> {customer} ({_dollars(amount_cents)})"
    )


HANDLERS = {
    "read_financials": _read_financials,
    "record_transaction": _record_transaction,
    "generate_invoice": _generate_invoice,
}
