---
name: invoicing-and-collections
title: Invoicing & Collections
description: Invoice accurately and collect promptly so earned revenue actually becomes cash.
roles: finance, growth
---
# Invoicing & Collections

Revenue you've earned but not collected doesn't pay the bills. This playbook invoices accurately
and collects on time, protecting cash and the customer relationship.

## Workflow
1. **Invoice from the real deal.** Pull terms from the closed deal (`crm_list_deals`) — amount,
   schedule, and what was agreed. `generate_invoice` with the correct figures; never invoice a
   number that doesn't match the signed terms.
2. **Send promptly and confirm receipt.** Late invoicing delays cash for no reason. `send_email`
   the invoice; `crm_log_activity` and `schedule_followup` for the due date.
3. **Track aging.** Monitor outstanding invoices by age (`read_financials`). The older a
   receivable, the less likely it collects — act before it ages.
4. **Dun professionally.** For overdue accounts, escalate gently: a reminder, then a firmer notice,
   then a call to resolve. Keep it factual and relationship-preserving; assume good faith first.
5. **Record collection.** When paid, `record_transaction` and reconcile against the invoice. Match
   payments to invoices — unapplied cash creates close problems (`monthly-financial-close`).
6. **Escalate real problems.** Persistent non-payment or disputes → `flag_legal_risk` /
   `request_decision`. `write_memory` (type `learning`) patterns (segments/terms that pay slowly).

## Decision framework — firmness vs. relationship
Be prompt and clear, but assume good faith until proven otherwise. Most late payment is
oversight, not refusal; preserve the relationship while protecting the cash.

## Definition of done
- Invoices match signed terms and are sent promptly; aging tracked.
- Overdue accounts dunned professionally; payments recorded and reconciled; disputes escalated.

## Common failure modes
- **Slow invoicing.** Delays cash for no reason.
- **Ignoring aging.** Old receivables quietly become bad debt.
- **Unreconciled payments.** Cash not matched to invoices breaks the close.
