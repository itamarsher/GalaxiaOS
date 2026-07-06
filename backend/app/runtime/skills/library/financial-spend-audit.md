---
name: financial-spend-audit
title: Financial Spend Audit
description: Independently audit the fleet's spending to confirm every charge was budgeted, justified, and recorded.
roles: auditor, finance
---
# Financial Spend Audit

The auditor role exists to independently verify the company's spending is legitimate. This playbook audits
the fleet's charges — confirming each was within budget, justified, and correctly recorded — as a check on
the operators, not a rubber stamp.

## Workflow
1. **Pull the spend record.** `read_financials` and the transaction history (`record_transaction` log) for
   the period. This includes both LLM token spend and external charges — all real money through the CostMeter.
2. **Reconcile against budget.** Confirm each charge fell within its category budget and the hard cap
   (`budget-planning-and-forecast`). Any spend that exceeded budget or bypassed reservation is a finding, not
   a footnote — the reserve-before-spend guarantee must hold.
3. **Test justification.** For material charges, was there a clear purpose tied to an objective and a
   decision/approval where required (`expense-approval-workflow`)? Spend with no traceable justification is flagged.
4. **Check recording accuracy.** Is every charge categorized correctly and matched to its purpose? Miscategorized
   or unrecorded spend corrupts the financials and hides problems (`monthly-financial-close`, `data-quality-audit`).
5. **Hunt for anomalies.** Duplicate charges, unexpected recurring costs, spend spikes, or anything
   circumventing controls. `flag_legal_risk` / `request_decision` on anything suggesting misuse or a broken control.
6. **Report independently.** `create_report` (kind `financial_report`) with findings and severity; `audit_task`
   the specific problem tasks; `write_memory` (type `result`). The auditor reports what it finds, plainly — its
   value is independence, not agreement.

## Decision framework — independence over harmony
The audit's worth comes from being willing to report uncomfortable findings. A clean report is only credible if
a dirty one was possible. Verify against the records; never assume the operators got it right because they usually do.

## Definition of done
- Full spend (LLM + external) pulled and reconciled to budget/cap; over-budget or unreserved spend flagged.
- Material charges justification-tested; recording accuracy checked; anomalies hunted; findings reported independently.

## Common failure modes
- **Rubber-stamping.** An audit that assumes correctness verifies nothing.
- **Missing the reserve guarantee.** Not catching spend that bypassed budget reservation.
- **Softening findings.** Undermining the independence that gives the audit its value.
