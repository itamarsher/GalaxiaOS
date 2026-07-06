---
name: customer-onboarding-flow
title: Customer Onboarding Flow
description: Design onboarding that gets a new customer to first value fast, cutting early churn.
roles: growth, product
---
# Customer Onboarding Flow

The gap between signup and first value is where customers churn silently. This playbook
designs onboarding that drives users to their "aha" moment quickly and measurably.

## Workflow
1. **Define first value ("aha").** Name the specific action that correlates with retention
   (the moment the product's value becomes real). If unknown, mine it from
   `cohort-analysis` / `read_metrics` — retained users share an early behavior.
2. **Map the current path.** Walk signup → first value as a new user. List every step, friction
   point, and drop-off. Each unnecessary step is a churn opportunity.
3. **Cut and sequence.** Remove steps that don't lead to value; sequence the rest so the user
   wins early. Defer nice-to-haves until after first value.
4. **Add guidance and nudges.** Draft welcome/onboarding emails (`draft_document` + `send_email`)
   and in-product prompts (`dispatch_task` to product). Trigger a `schedule_followup` for users
   who stall before first value.
5. **Instrument the funnel.** `record_metric` for signup → activated (reached first value) →
   retained. This is the number onboarding exists to move.
6. **Iterate on the biggest drop.** `write_memory` (type `experiment`) one change to the largest
   drop-off step, ship it, and re-measure (`landing-page-optimization` discipline).

## Decision framework — time-to-value
Optimize for shortest honest path to first value, not feature coverage. A user who succeeds
once comes back; a user who's overwhelmed leaves.

## Definition of done
- First-value action defined and instrumented; friction steps removed.
- Activation rate measured; one drop-off improvement shipped and re-measured.

## Common failure modes
- **Feature tours instead of value.** Showing everything delays the one thing that matters.
- **No activation metric.** You can't improve what you don't measure.
- **Ignoring stalled users.** A timely nudge recovers otherwise-lost customers.
