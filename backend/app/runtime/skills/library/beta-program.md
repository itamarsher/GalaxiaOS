---
name: beta-program
title: Beta Program
description: Run a structured beta that produces real feedback and readiness signal before general availability.
roles: product, growth
---
# Beta Program

A beta de-risks a launch by exposing a feature to real users under controlled conditions. This
playbook runs one that yields honest feedback and a clear go/no-go signal.

## Workflow
1. **Define beta goals.** What must the beta prove — usability, stability, value, willingness to
   pay? Set the exit criteria for GA before starting. `write_memory` (type `experiment`).
2. **Recruit the right cohort.** `crm_find_contacts` for engaged, representative users who'll
   actually use it and give feedback. Small and committed beats large and passive.
3. **Set expectations.** Tell beta users it's early, what to expect, and how to report issues.
   Managed expectations prevent goodwill damage from rough edges.
4. **Instrument and support.** `record_metric` for adoption and key flows; open a feedback channel
   (`start_chat_channel`); triage reports via `report_bug` / `list_feature_requests`.
5. **Close the loop.** Respond to feedback and fix blockers fast — beta users who feel heard become
   advocates. `dispatch_task` fixes to platform.
6. **Decide GA.** `write_memory` (type `result`): did it meet the exit criteria? If yes, plan the
   launch (`product-launch-gtm`); if no, name the gaps and iterate — don't ship on a deadline alone.

## Decision framework — extend or ship
Ship to GA only when exit criteria are met, not when the calendar says so. A beta that reveals a
blocker has done its job; ignoring it to hit a date defeats the purpose.

## Definition of done
- GA exit criteria set upfront; representative cohort recruited with clear expectations.
- Feedback instrumented and acted on; explicit, criteria-based GA decision recorded.

## Common failure modes
- **Beta as a countdown, not a test.** Shipping regardless of signal wastes the beta.
- **Passive cohort.** Users who don't engage give no signal.
- **Ignoring feedback.** Unheard beta users churn and warn others.
