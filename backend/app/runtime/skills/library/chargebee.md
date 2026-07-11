---
name: chargebee
title: Chargebee
description: Set up subscription plans, handle recurring billing, dunning, proration, revenue recognition, or tax in Chargebee.
roles: finance
---
# Chargebee

Chargebee is the fleet's subscription-billing engine — plans, recurring invoices, dunning, proration, and
ASC 606 revenue recognition. The ABOS-adapted rule: **connect it as a tool first, never assume it's wired**,
and because it bills real customers on a schedule, **mirror every charge in the ledger and never invent an
invoice**.

## Connect before you bill
1. **Find the tool.** `discover_tools` with query `chargebee`; it exposes as `mcp__chargebee__*` once the
   founder connects it. Load what you need with `use_tool` (create plan, subscription, read invoices).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Chargebee in
   Settings (site + API key). Never invent a subscription, invoice, or MRR figure — a phantom invoice is
   worse than none. If the capability can't exist yet, `request_capability`.
3. **Gate pricing changes.** A price, plan, or dunning change affects real customer charges; for material
   changes `request_decision` and confirm against `get_company_playbook`.

## Run subscription billing the way pros do
4. **Model plans cleanly.** Use tiered/volume/flat pricing with explicit trials and coupons; let Chargebee
   handle proration automatically on mid-cycle upgrades/downgrades rather than hand-computing credits.
5. **Configure dunning to recover, not churn.** Enable smart retries, dunning emails, and hosted
   card-update pages so failed payments recover before cancellation — recovered revenue is the point.
6. **Revenue recognition on rails.** Turn on ASC 606 / IFRS 15 recognition so billed revenue is audit-ready,
   and sync to the GL (QuickBooks/NetSuite/Xero) — don't recognize cash as revenue at charge time.
7. **Tax by location.** Configure VAT/GST/US sales tax (Avalara) by customer region; wrong tax is a
   compliance liability, so `check_compliance` / `flag_legal_risk` on new jurisdictions.

## Mirror it in ABOS and file it
8. **Record and reconcile.** `generate_invoice` / `record_transaction` mirror what Chargebee bills, and
   `read_financials` / `record_metric` MRR and churn from real data — never estimate revenue.
9. **File statements.** `save_file` invoices and revenue reports (category `financial`) with the Chargebee
   link; `write_memory` (type `result`) and `report_result`.

## Definition of done
- Chargebee confirmed connected (or escalated, never faked); material pricing/dunning changes decided.
- Plans modeled with auto-proration, dunning tuned to recover, ASC 606 on, tax by region checked.
- Charges mirrored via `generate_invoice`/`record_transaction`, reports `save_file`d (financial).

## Common failure modes
- **Phantom invoice.** Reporting revenue or a subscription Chargebee was never connected to bill — escalate.
- **Dunning left off.** Failed cards silently churn instead of retrying, quietly bleeding MRR.
- **Wrong tax/recognition.** Mis-set jurisdiction tax or cash-basis recognition that breaks the audit.
