---
name: referral-program-launch
title: Referral Program Launch
description: Design and launch a referral program that turns happy customers into a measurable acquisition channel.
roles: growth, ceo
---
# Referral Program Launch

Referrals are the cheapest, highest-trust leads a company gets. This playbook stands up a
small, instrumented referral program and proves it works before scaling the incentive.

## Workflow
1. **Find your promoters.** Referrals only work from genuinely happy customers. Pull NPS /
   testimonial signals (`read_metrics`, `crm_find_contacts`) — don't ask detractors to refer.
2. **Design the incentive.** Pick a two-sided reward (referrer + referee) that is generous
   enough to motivate but within margin. Any cash/credit reward is real spend — `request_budget`
   for the program cap before launching.
3. **Define the mechanics** simply: who qualifies, what triggers the reward, and how it's paid.
   Complexity kills participation.
4. **Instrument it.** Set the success metric (e.g. referral-sourced signups, CAC vs. paid).
   `write_memory` (type `experiment`) the hypothesis and target.
5. **Launch to a small cohort first.** Reach promoters via `send_email`; announce with
   `publish_content` / `schedule_social_post` only after the cohort validates it works.
6. **Track and pay.** Log referred leads with `log_lead`; attribute deals via `crm_save_deal`.
   Reward fulfillment that moves money goes through `record_transaction`.
7. **Measure and decide.** `record_metric` for referral CAC and volume; scale the incentive
   only if CAC beats paid channels.

## Decision framework — reward size
Start at the smallest reward that still feels worth sharing. You can raise a stingy reward;
clawing back a generous one destroys trust.

## Definition of done
- Promoter-sourced list, budgeted incentive, and a single success metric defined.
- Piloted to a cohort before broad launch; referral CAC recorded.

## Common failure modes
- **Asking everyone to refer.** Detractors amplify dissatisfaction.
- **Baroque mechanics.** If it needs a diagram to understand, participation collapses.
- **Unbudgeted rewards.** Referral payouts are real money — reserve them first.
