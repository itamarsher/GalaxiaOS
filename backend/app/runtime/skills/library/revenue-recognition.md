---
name: revenue-recognition
title: Revenue Recognition
description: Recognize revenue in the period it's earned, not merely when cash arrives, for honest financials.
roles: finance, auditor
---
# Revenue Recognition

Cash received is not the same as revenue earned. This playbook applies consistent recognition so
the financials reflect economic reality — critical for trust, fundraising, and audit.

## Workflow
1. **Identify the obligation.** For each sale, what did we promise and over what period? A 12-month
   prepaid plan is delivered over 12 months, not earned all in month one.
2. **Match revenue to delivery.** Recognize revenue as the obligation is fulfilled: subscriptions
   ratably over the term, one-time services when delivered, usage as consumed.
3. **Handle upfront cash correctly.** Cash collected ahead of delivery is deferred revenue (a
   liability), recognized over time. Don't book it all as current revenue — that overstates the period.
4. **Apply consistently.** Use the same policy every period so comparisons are meaningful. Document
   the policy in `update_company_playbook`; changing it midstream distorts trends.
5. **Reconcile with cash and the close.** Cross-check recognized revenue against `record_transaction`
   cash and the deal terms during `monthly-financial-close`. Investigate mismatches.
6. **Report and flag.** `record_metric` for recognized vs. deferred revenue; `flag_legal_risk` /
   `request_decision` on unusual arrangements (multi-element deals, refunds, contingent terms).

## Decision framework — earned vs. collected
When in doubt, recognize more conservatively (later), not aggressively (earlier). Overstated
revenue is a serious integrity and legal problem; understatement is merely cautious.

## Definition of done
- Each sale's obligation and delivery period identified; revenue matched to delivery.
- Upfront cash deferred correctly; policy consistent and documented; unusual deals flagged.

## Common failure modes
- **Booking all prepaid cash as current revenue.** Overstates the period and misleads everyone.
- **Inconsistent policy.** Makes period-over-period trends meaningless.
- **Aggressive recognition.** An integrity and legal risk; err conservative.
