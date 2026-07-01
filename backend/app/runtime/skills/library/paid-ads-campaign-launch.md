---
name: paid-ads-campaign-launch
title: Paid Ads Campaign Launch
description: Launch a small, budgeted paid-ads test and measure it against a target CAC before scaling.
roles: growth, ceo
---
# Paid Ads Campaign Launch

Stand up a small paid-acquisition test that either earns more budget by hitting a target
CAC, or gets killed cheaply. Never scale spend before the numbers justify it.

## Workflow
1. **Set the bet and the budget.** State the hypothesis: which segment, which channel, and the
   single success metric (target CAC or cost-per-lead). Record it with `write_memory` (type
   `experiment`). The campaign spends real money, so `request_budget` for the test amount first
   and wait for approval — do not launch on assumed budget.
2. **Prepare creative and destination.** Commission ad creative from design via `dispatch_task`,
   or brief it and generate visuals with `generate_image`. Point ads at a specific landing page,
   not the homepage; if it doesn't exist, `dispatch_task` to build it (`landing-page-optimization`).
3. **Launch.** Use `run_ad_campaign` with the approved budget cap and target segment. If it
   reports the channel/capability is unsupported, STOP and `request_capability` — do not claim
   ads are live when they are not.
4. **Measure against the target.** As spend and results land, `record_metric` for spend, leads/
   conversions, and derived CAC. Log qualified leads with `log_lead` for sales pickup. Use
   measured values only — no projections.
5. **Decide: kill, iterate, or scale.**
   - Below target CAC → `request_budget` to scale; `write_memory` (type `result`) the winning segment/creative.
   - Above target → kill it; `write_memory` the learning; propose the next variant.
   - Either way, `report_result` with the CAC and the decision.

## Decision framework — scale gate
Only scale a channel whose CAC beats your blended target AND whose leads convert downstream
(check with sales, not just click data). Cheap clicks that never close are expensive.

## Definition of done
- Budget approved before launch; one hypothesis and success metric.
- CAC measured from real spend/results; explicit kill/iterate/scale decision recorded.

## Common failure modes
- **Launching on assumed budget.** Ad spend is real money — reserve it first.
- **Optimizing clicks, not closes.** Judge on downstream conversion.
- **Scaling a fluke.** One good day isn't signal; wait for a stable sample.
