---
name: churn-reduction-playbook
title: Churn Reduction Playbook
description: Find why customers leave, intervene where it pays, and measure retention improvement.
roles: growth, product, finance
---
# Churn Reduction Playbook

Retention compounds; churn quietly caps growth. This playbook finds the real churn drivers,
intervenes where the economics justify it, and proves the improvement.

## Workflow
1. **Measure churn honestly.** `read_metrics` / `read_financials` for logo and revenue churn.
   Distinguish voluntary (chose to leave) from involuntary (failed payment) — the fixes differ.
2. **Find the drivers.** `cohort-analysis` to see who churns and when; pull reasons from exit
   signals and `crm_contact_timeline`. `write_memory` (type `learning`) the top 2–3 drivers.
3. **Segment by value.** Not all churn is equal — prioritize interventions for high-value or
   high-potential segments (`read_financials`). Saving unprofitable churn can cost more than it's worth.
4. **Intervene at the driver:**
   - *Onboarding-driven* → fix `customer-onboarding-flow`.
   - *Value-realization* → proactive check-ins / `send_email` before the risk window.
   - *Involuntary* → dunning/payment retry (`dispatch_task` to platform/finance).
5. **Test one intervention.** `write_memory` (type `experiment`) the hypothesis; apply to a
   cohort; `record_metric` retained vs. control.
6. **Bank and scale.** `write_memory` (type `result`); roll out what works; `update_company_playbook`.

## Decision framework — save or let go
Intervene where (expected retained value) > (cost of intervention). Chasing every churned user,
including unprofitable ones, is itself a form of waste.

## Definition of done
- Voluntary vs. involuntary split; top drivers identified; high-value segments prioritized.
- One intervention tested against a control; retention impact recorded.

## Common failure modes
- **Treating all churn the same.** Payment failures and value gaps need different fixes.
- **Saving unprofitable customers** at a loss.
- **No control.** Without a comparison you can't tell if the intervention worked.
