---
name: bill-com
title: Bill.com
description: Automate accounts payable or receivable, route bills through approvals, pay vendors by ACH or check, or capture invoices via OCR in Bill.com.
roles: finance
---
# Bill.com

Bill.com (BILL) is the fleet's AP/AR engine — invoice capture, approval routing, ACH/check/wire payments,
and an audit trail on every bill. The ABOS-adapted rule: **connect it as a tool first, never assume it's
wired**, and because paying a bill moves real money irreversibly, **gate the payment, don't just click it**.

## Connect before you pay
1. **Find the tool.** `discover_tools` with query `bill.com`; it exposes as `mcp__bill-com__*` once the
   founder connects it. Load what you need with `use_tool` (read bill, route approval, schedule payment).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect BILL in
   Settings (API key + org ID). Never invent an invoice, vendor, or payment confirmation — a phantom bill
   is worse than none. If the capability can't exist yet, `request_capability`.
3. **Gate the money.** Scheduling an ACH or check is real, hard-to-claw-back spend. `request_budget`
   before a payment run and `request_decision` for large or first-time-vendor payments.

## Run AP/AR the way pros do
4. **Centralize intake, trust the OCR — then verify.** Route all invoices to one BILL inbox so nothing
   is missed; let BILL AI extract fields and line items, but confirm amount, vendor, and GL coding before
   approval — OCR is fast, not infallible.
5. **Approval rules, not manual routing.** Configure routing by amount, department, and vendor so bills
   reach the right approver automatically; respect the gate, never pay around an unapproved bill.
6. **Match before you release.** Reconcile bill to PO/receipt and confirm vendor bank details out-of-band
   — payment-detail change requests are the classic invoice-fraud vector; `flag_legal_risk` if suspicious.
7. **Batch payment runs.** Group approved bills into ACH runs on a schedule for a single control point
   rather than one-off wires.

## Mirror it in ABOS and file it
8. **Record every payment.** `record_transaction` each bill paid and `read_financials` to reconcile AP
   against real balances; on the AR side `generate_invoice` mirrors what BILL bills out.
9. **File the trail.** `save_file` remittances and statements (category `financial`) with the BILL link;
   `write_memory` (type `result`) and `report_result`. For tax/1099 handling, `check_compliance`.

## Definition of done
- BILL confirmed connected (or escalated, never faked); payment runs budgeted and, if large, decided.
- Invoices captured, coded, approved through the rules; vendor bank details verified.
- Payments recorded, remittances `save_file`d (financial), outcome recorded.

## Common failure modes
- **Phantom invoice.** Claiming a bill was paid when BILL was never connected — escalate instead.
- **Fraudulent bank change.** Paying a spoofed "updated details" request without out-of-band verification.
- **Routing around approval.** Releasing an unapproved or miscoded bill that breaks the audit trail.
