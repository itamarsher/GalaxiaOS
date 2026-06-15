"""Legal tools: document drafting, compliance screening, and risk flagging.

Area-specific tools for the legal/governance function. Everything here is
deterministic and SIMULATED — drafts are templated skeletons (no LLM, no
network), the compliance check is a pure keyword scan, and risk flags are
surfaced to the founder's inbox as a non-blocking ``DecisionRequest`` row.

None of these tools is authoritative legal advice; drafts and reviews are
explicitly labelled as requiring human/lawyer sign-off before use.
"""

from __future__ import annotations

from app.models import Agent, DecisionRequest, Task
from app.models.enums import DecisionKind, DecisionStatus, MemoryType
from app.providers.base import ToolSpec
from app.runtime.tools.base import ToolOutcome
from app.services import memory as memory_svc

#: Document templates we can produce a deterministic skeleton for.
DOC_TYPES: tuple[str, ...] = ("nda", "tos", "privacy_policy", "service_agreement", "other")

#: Allowed severities for a flagged legal risk, in ascending order.
SEVERITIES: tuple[str, ...] = ("low", "medium", "high")

#: Risk keywords the simulated compliance scan looks for in an action string.
RISK_KEYWORDS: tuple[str, ...] = (
    "pii",
    "personal data",
    "health",
    "medical",
    "payment",
    "credit card",
    "minor",
    "children",
    "gdpr",
    "hipaa",
    "ccpa",
    "biometric",
    "export",
)

#: Human-readable titles for the templated document headers.
_DOC_TITLES: dict[str, str] = {
    "nda": "Non-Disclosure Agreement",
    "tos": "Terms of Service",
    "privacy_policy": "Privacy Policy",
    "service_agreement": "Service Agreement",
    "other": "Legal Document",
}


def scan_compliance(action: str) -> list[str]:
    """Pure, deterministic keyword scan over ``action``.

    Returns the sorted list of risk keywords present in the action text. This is
    a simulated, non-authoritative heuristic — never network or LLM backed.
    """
    text = (action or "").lower()
    return sorted({kw for kw in RISK_KEYWORDS if kw in text})


def build_draft(doc_type: str, counterparty: str | None, key_terms: list[str] | None) -> str:
    """Build a deterministic, templated plain-text draft skeleton."""
    title = _DOC_TITLES.get(doc_type, _DOC_TITLES["other"])
    party = counterparty or "[COUNTERPARTY]"
    lines = [
        title.upper(),
        "=" * len(title),
        "",
        f"Document type: {doc_type}",
        f"Between: [COMPANY] and {party}",
        "",
        "1. PARTIES",
        f"   This {title.lower()} is entered into by [COMPANY] and {party}.",
        "",
        "2. PURPOSE",
        f"   Sets out the terms governing the {title.lower()} between the parties.",
        "",
        "3. KEY TERMS",
    ]
    if key_terms:
        for i, term in enumerate(key_terms, start=1):
            lines.append(f"   3.{i} {term}")
    else:
        lines.append("   3.1 [TO BE COMPLETED]")
    lines += [
        "",
        "4. CONFIDENTIALITY",
        "   [TO BE COMPLETED]",
        "",
        "5. TERM AND TERMINATION",
        "   [TO BE COMPLETED]",
        "",
        "6. GOVERNING LAW",
        "   [TO BE COMPLETED]",
        "",
        "7. SIGNATURES",
        "   [COMPANY]: ____________________   Date: __________",
        f"   {party}: ____________________   Date: __________",
        "",
        "--",
        "DRAFT ONLY — templated skeleton, not legal advice. A qualified human "
        "lawyer must review and complete this document before use.",
    ]
    return "\n".join(lines)


SPECS: list[ToolSpec] = [
    ToolSpec(
        name="draft_document",
        description=(
            "Produce a deterministic templated draft of a legal document "
            "(nda|tos|privacy_policy|service_agreement|other) and save it to memory. "
            "Skeleton only — a human/lawyer must review before use."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "doc_type": {
                    "type": "string",
                    "enum": list(DOC_TYPES),
                },
                "counterparty": {
                    "type": "string",
                    "description": "Other party to the document, if known.",
                },
                "key_terms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Bullet terms to seed the KEY TERMS section.",
                },
            },
            "required": ["doc_type"],
        },
    ),
    ToolSpec(
        name="check_compliance",
        description=(
            "Run a simulated, non-authoritative compliance review of an action: "
            "scans for risk keywords (pii, health, payment, gdpr, hipaa, ...) and "
            "reports any matches. Not legal advice."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action or plan to screen for compliance risk.",
                },
                "jurisdiction": {
                    "type": "string",
                    "description": "Optional jurisdiction context (free text).",
                },
            },
            "required": ["action"],
        },
    ),
    ToolSpec(
        name="flag_legal_risk",
        description=(
            "Surface a legal risk to the founder's inbox as a non-blocking decision "
            "request. Does NOT pause the task."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What the legal risk is."},
                "severity": {
                    "type": "string",
                    "enum": list(SEVERITIES),
                },
            },
            "required": ["summary", "severity"],
        },
    ),
]


async def _draft_document(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    doc_type = args["doc_type"]
    if doc_type not in DOC_TYPES:
        return ToolOutcome(
            observation=(
                f"invalid doc_type {doc_type!r}; expected one of {', '.join(DOC_TYPES)}"
            ),
            is_error=True,
        )
    draft = build_draft(doc_type, args.get("counterparty"), args.get("key_terms"))
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.decision,
        title=f"Draft {doc_type}",
        content=draft,
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=(
            f"drafted {doc_type} (templated skeleton) and saved to memory; "
            "a human/lawyer should review before use"
        )
    )


async def _check_compliance(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    action = args["action"]
    jurisdiction = args.get("jurisdiction")
    flags = scan_compliance(action)
    where = f" [{jurisdiction}]" if jurisdiction else ""
    if flags:
        finding = "potential issues flagged: " + ", ".join(flags)
    else:
        finding = "no blocking issues found (simulated review)"
    await memory_svc.write(
        db,
        company_id=task.company_id,
        type=MemoryType.result,
        title=f"Compliance check{where}: {action[:60]}",
        content=f"Simulated, non-authoritative review of {action!r}{where}.\n{finding}",
        source_task_id=task.id,
    )
    return ToolOutcome(
        observation=f"simulated compliance review{where} — {finding} (not legal advice)"
    )


async def _flag_legal_risk(db, ctx, *, agent: Agent, task: Task, args: dict) -> ToolOutcome:
    severity = str(args["severity"]).strip().lower()
    if severity not in SEVERITIES:
        return ToolOutcome(
            observation=(
                f"invalid severity {args['severity']!r}; expected one of "
                f"{', '.join(SEVERITIES)}"
            ),
            is_error=True,
        )
    summary = args["summary"]
    db.add(
        DecisionRequest(
            company_id=task.company_id,
            agent_id=agent.id,
            task_id=task.id,
            kind=DecisionKind.risky_action,
            summary=f"[legal risk: {severity}] {summary}",
            status=DecisionStatus.pending,
        )
    )
    await db.flush()
    return ToolOutcome(
        observation=f"flagged {severity} legal risk to founder inbox (non-blocking): {summary[:80]}"
    )


HANDLERS = {
    "draft_document": _draft_document,
    "check_compliance": _check_compliance,
    "flag_legal_risk": _flag_legal_risk,
}
