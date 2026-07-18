"""Finance tools: budget/metrics visibility and transaction recording.

``read_financials`` and ``record_transaction`` operate on the company's OWN data —
they read the real monthly :class:`Budget` / metric signals and record observed
revenue/expense to metrics and institutional memory — so they are genuine internal
operations and stay.

``generate_invoice`` is different: issuing an invoice means billing a real customer
through a real billing provider, and none is connected. It used to fabricate an
invoice id and log it as "invoiced" revenue, which is exactly the kind of fake
outcome that misleads planning, so it now reports the capability is unavailable and
points the agent at ``request_capability``.
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import Agent, Budget, Task
from app.models.enums import BudgetPeriod, MemoryType, MetricSource
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome, unsupported_capability
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
            "Issue a customer invoice via the billing provider. Does not charge the "
            "company budget (it bills a customer, not the company)."
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
        labels=["financial"],
    )
    # Best-effort: drop a record into the company's Financials folder so the audit
    # trail accretes in external storage too. Never blocks the transaction — no-ops
    # when no file provider is connected.
    from app.models.enums import FileCategory
    from app.services import files as files_svc

    await files_svc.safe_archive(
        db,
        company_id=task.company_id,
        category=FileCategory.financial,
        name=f"transaction-{kind}-{_dollars(amount_cents).replace('$', '').replace(',', '')}",
        content=f"# {kind.title()} — {_dollars(amount_cents)}\n\n{content}",
        source_task_id=task.id,
        description=f"{kind} {_dollars(amount_cents)}",
    )
    return ToolOutcome(observation=f"recorded {detail}")


async def _generate_invoice(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    return unsupported_capability(
        "Generating a customer invoice",
        hint="No billing/invoicing provider is connected to issue the invoice.",
    )


HANDLERS = {
    "read_financials": _read_financials,
    "record_transaction": _record_transaction,
    "generate_invoice": _generate_invoice,
}
