---
name: quickbooks
title: QuickBooks
description: Categorize transactions, reconcile accounts, issue invoices, handle sales tax, or run the month-end close in QuickBooks when the company's books live there.
roles: finance
---
# QuickBooks

QuickBooks is the fleet's general ledger — every dollar in and out lands in its chart of accounts. The
books are a system of record, so the ABOS-adapted principle is: **connect it as a tool first, never
assume it's wired, and never invent a number.** Read real balances or escalate; a fabricated entry is a
false financial statement.

## Connect before you post
1. **Find the tool.** `discover_tools` query `quickbooks`; it exposes as `mcp__quickbooks__*` once the
   founder connects it. Load what you need with `use_tool`.
2. **Not connected? Escalate — don't fake it.** `request_user_action` for the founder to connect
   QuickBooks Online (OAuth) in Settings. Never invent an invoice, balance, or reconciliation result.
3. **Books changes are gated.** Posting entries, issuing invoices, or closing a period are material — get
   `request_decision` (founder sign-off) before locking a period or moving real money.

## Keep the books clean
4. **Chart of accounts is the backbone.** Keep it lean — Assets, Liabilities, Equity, Income, Expenses —
   and categorize every transaction into the right account. Don't spawn one-off accounts; a clean COA is
   the whole basis of a stress-free close.
5. **Reconcile monthly against the bank.** Match every account to its statement to catch duplicate,
   missing, or fraudulent transactions. Clear Undeposited Funds — it silently misstates revenue and
   sales tax if left to pile up.
6. **Sales tax via the Sales Tax Center, never journal entries.** Set the correct agency, rates, and
   taxable vs non-taxable items; let QuickBooks compute liability. Fixing tax with manual JEs corrupts
   the filing — route tax/regulatory questions through `check_compliance` / `flag_legal_risk`.
7. **Run the close checklist and lock it.** Reconcile all accounts, review P&L and balance sheet, then
   close the books with a password so the period can't be backdated or edited.

## Record and file it
8. **Mirror and export.** `record_transaction` and `generate_invoice` so ABOS mirrors QuickBooks;
   `read_financials` to pull real balances. `save_file` the close pack / reports (category `financial`).
9. **Report.** `record_metric` on revenue/burn, `write_memory` (type `result`), then `report_result`.

## Definition of done
- QuickBooks confirmed connected (or escalated, never faked); period lock gated by decision.
- All accounts reconciled, sales tax set correctly, close checklist run and books locked.
- Entries mirrored via `record_transaction`, reports filed, outcome recorded.

## Common failure modes
- **Phantom balance.** Reporting a figure QuickBooks never held — read real data or escalate.
- **Sales-tax journal entries.** Hand-adjusting tax instead of using the Sales Tax Center, breaking filings.
- **Unreconciled close.** Locking a period before accounts tie to the bank, baking in errors.
