---
name: monthly-financial-close
title: Monthly Financial Close
description: Reconcile the month's transactions into a clean, trustworthy set of financials.
roles: finance, auditor
---
# Monthly Financial Close

The close turns a month of raw transactions into numbers the fleet and founder can trust. This
playbook runs it in a repeatable, auditable way — accuracy over speed.

## Workflow
1. **Pull the period's activity.** `read_financials` and the transaction log for the month.
   Establish the opening and expected closing position.
2. **Reconcile every category.** Match recorded transactions (`record_transaction` history) to
   actual spend and revenue. Investigate discrepancies — an unexplained gap is a red flag, not a
   rounding issue. Never plug a number to make it balance.
3. **Classify correctly.** Ensure each transaction is in the right category (COGS vs. opex,
   one-time vs. recurring). Miscategorization distorts every downstream metric.
4. **Recognize revenue properly.** Apply `revenue-recognition` — cash received is not always
   revenue earned this period.
5. **Produce the statements.** Summarize income, spend by category, and cash/runway position.
   `create_report` (kind `financial_report`) with the month's numbers and notable variances.
6. **Flag and file.** `flag_legal_risk` / `request_decision` on anything anomalous; `write_memory`
   (type `result`) the closing position; store the report (`save_file`).

## Decision framework — accuracy vs. speed
A late-but-correct close beats an on-time wrong one. If a number can't be reconciled, report it as
open with an explanation rather than guessing.

## Definition of done
- Every category reconciled to actuals; discrepancies investigated, not plugged.
- Revenue recognized correctly; statements produced; anomalies flagged; position recorded.

## Common failure modes
- **Plugging gaps.** Forcing a balance hides the very problem the close exists to catch.
- **Miscategorization.** One misclassified cost corrupts margin and unit economics.
- **Confusing cash with revenue.** Recognition rules exist for a reason.
