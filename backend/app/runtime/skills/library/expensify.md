---
name: expensify
title: Expensify
description: Build expense reports, scan receipts with SmartScan, route approvals, or enforce corporate-card policy rules in Expensify.
roles: finance
---
# Expensify

Expensify is the fleet's expense-report and receipt layer — SmartScan capture, policy rules, multi-level
approvals, and corporate-card reconciliation. The ABOS-adapted rule: **connect it as a tool first, never
assume it's wired**, and because approved reports become real reimbursements, **respect the approval gate
and mirror actual spend, never invent a receipt or a report**.

## Connect before you submit
1. **Find the tool.** `discover_tools` with query `expensify`; it exposes as `mcp__expensify__*` once the
   founder connects it. Load what you need with `use_tool` (create report, read expenses, submit).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Expensify in
   Settings (partner user ID + secret). Never invent a receipt, expense, or approval — a phantom report is
   worse than none. If the capability can't exist yet, `request_capability`.
3. **Gate reimbursement.** An approved report triggers a real reimbursement; `request_budget` before a
   reimbursement run and `request_decision` for large or out-of-policy amounts.

## Run expense management the way pros do
4. **Trust SmartScan, then verify.** Let SmartScan extract merchant/amount/date and auto-match to card
   transactions, but confirm coding before approval — capture is fast, not a substitute for review.
5. **Encode policy as rules.** Set category limits, receipt thresholds (e.g. require receipts over $25/$75),
   and submission deadlines in the policy so violations flag automatically instead of in manual review.
6. **Tiered approval by threshold.** Configure multi-level workflows that route by spend amount so routine
   expenses flow and large ones escalate; respect the gate, never approve around it.
7. **Reconcile card to receipt.** Chase unmatched card transactions and missing receipts — the unmatched
   set is the audit and compliance gap. Code cleanly to the GL for sync.

## Mirror it in ABOS and file it
8. **Record the spend.** `record_transaction` reimbursed/coded expenses and `read_financials` to reconcile
   against real card and cash balances — mirror Expensify, never estimate.
9. **File reports.** `save_file` exported expense reports and receipts (category `financial`) with the
   Expensify link; `write_memory` (type `result`) and `report_result`. Tax coding: `check_compliance`.

## Definition of done
- Expensify confirmed connected (or escalated, never faked); reimbursement runs budgeted and, if large, decided.
- SmartScan verified, policy rules enforcing limits/receipts/deadlines, tiered approvals, card-to-receipt matched.
- Expenses recorded, reports `save_file`d (financial), outcome recorded.

## Common failure modes
- **Phantom report.** Claiming an expense or reimbursement when Expensify was never connected — escalate instead.
- **Policy as afterthought.** No encoded limits/deadlines, so violations surface only in slow manual review.
- **Unmatched card spend.** Card transactions without receipts left unreconciled, breaking the audit trail.
