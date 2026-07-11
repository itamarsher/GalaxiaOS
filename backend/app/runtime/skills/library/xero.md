---
name: xero
title: Xero
description: Reconcile bank feeds, code transactions, raise invoices, handle multi-currency, or pull financial reports in Xero when the company's books live there.
roles: finance
---
# Xero

Xero is the fleet's cloud ledger — bank feeds flow in daily and every transaction gets coded against the
chart of accounts. The books are a system of record, so the ABOS-adapted principle is: **connect it as a
tool first, never assume it's wired, and never invent a number.** Read real balances or escalate; a
fabricated entry is a false financial statement.

## Connect before you reconcile
1. **Find the tool.** `discover_tools` query `xero`; it exposes as `mcp__xero__*` once the founder
   connects it. Load what you need with `use_tool`.
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Xero
   (OAuth) in Settings. Never invent an invoice, reconciliation, or balance.
3. **Books changes are gated.** Coding, invoicing, and locking a period are material — `request_decision`
   (founder sign-off) before locking a period or moving real money.

## Reconcile like a pro
4. **Reconcile daily off the bank feed.** Feeds pull transactions automatically; do it in small daily
   passes, not a monthly avalanche. Confirm each account's opening balance matches the bank statement —
   a wrong opening balance carries through every later reconciliation.
5. **Bank rules for the repetitive stuff.** Configure rules and use suggested matches for recurring
   transactions so only genuine exceptions need a human. Don't blindly accept a suggested match — verify
   the contact and account first.
6. **Separate account per currency.** For multi-currency, create a distinct Xero bank account for each
   currency so FX isn't miscalculated. Watch the rate Xero auto-applies — it may differ from the bank's;
   review realized/unrealized gains before period end.
7. **Confirm with the reports.** After reconciling, open the Bank Reconciliation report to verify Xero's
   balance ties to the bank, and review the P&L and balance sheet before you call a period done.

## Record and file it
8. **Mirror and export.** `record_transaction` and `generate_invoice` so ABOS mirrors Xero;
   `read_financials` to pull real balances. `save_file` the report pack (category `financial`). Route
   tax/regulatory questions through `check_compliance`.
9. **Report.** `record_metric` on revenue/burn, `write_memory` (type `result`), then `report_result`.

## Definition of done
- Xero confirmed connected (or escalated, never faked); period lock gated by decision.
- Bank feed reconciled to statement, rules verified, multi-currency accounts split and FX reviewed.
- Entries mirrored via `record_transaction`, reports filed, outcome recorded.

## Common failure modes
- **Phantom balance.** Reporting a figure Xero never held — read real data or escalate.
- **Wrong opening balance.** A mismatched starting figure that quietly corrupts every reconciliation.
- **Blind rule-matching.** Accepting suggested matches without checking the contact, miscoding revenue.
