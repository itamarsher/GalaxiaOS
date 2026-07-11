---
name: pandadoc
title: PandaDoc
description: Build a proposal or quote, manage the content library, route approvals, or send a document for e-signature in PandaDoc — a gated outbound comm.
roles: growth, finance
---
# PandaDoc

PandaDoc is where the fleet turns deals into signable documents — proposals, quotes, and contracts from
reusable templates with e-signature and analytics. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, and remember that sending a document for signature
is a gated external comm that binds the company — never route around the approval gate. ABOS `crm_*` deals
stay the source of truth.

## Connect before you send
1. **Find the tool.** `discover_tools` with query `pandadoc`; it exposes as `mcp__pandadoc__*` once the
   founder has connected it. Load what you need with `use_tool` (create from template, send, read status).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect PandaDoc in
   Settings (MCP server or API key). Never invent a document link, signed status, or contract value — a
   phantom agreement is a legal and financial hazard.
3. **Signing is gated.** E-signature requests are indexed external comms that create obligations; pull deal
   terms from `crm_find_contacts`/deals and `request_decision` before sending any contract or priced quote —
   don't self-approve a binding document.

## Build documents that close
4. **Templates cover 80%, fields fill the rest.** Invest in well-designed, on-brand templates with
   placeholder fields and pricing tables; a template is reused hundreds of times, so setup pays back fast.
5. **Lock the content library.** Load pre-approved sections into the content library and lock them so reps
   assemble from vetted, brand-consistent blocks rather than editing legal or pricing language freely.
6. **Route approvals before signature.** Configure approval workflows keyed to discount threshold or deal
   size so quotes clear the right people first; in ABOS that gate is `request_decision` — respect it.
7. **Read the analytics.** Track opens, time-per-section, and views to time follow-up and spot stalled deals.

## File the deliverable and record it
8. **File the executed doc.** On signature, `save_file` (category `financial` for a signed contract/quote,
   else `artifact`) with the PandaDoc link — the durable record, not agent memory.
9. **Record + hand off.** `update_deal`/`crm_save_deal` with the signed value and stage, `record_metric` the
   close, `write_memory` (type `result`), then `report_result` or `dispatch_task` finance for invoicing.

## Definition of done
- PandaDoc confirmed connected (or escalated, never faked); a binding send cleared via `request_decision`.
- Built from locked, on-brand templates; approval workflow routed before signature.
- Executed document `save_file`d, deal updated in ABOS CRM, outcome recorded.

## Common failure modes
- **Ungated send.** Firing a contract for signature with no `request_decision` — an unauthorized obligation.
- **Phantom agreement.** Claiming a doc is sent or signed when PandaDoc was never connected — escalate.
- **Freehand pricing.** Reps editing unlocked legal or price content, so every proposal drifts off-approval.
