---
name: deal-pipeline-review
title: Deal Pipeline Review
description: Run a disciplined pipeline review that keeps stages honest and forecasts credible.
roles: growth, ceo, finance
---
# Deal Pipeline Review

Pipeline rots without review: deals sit in stages they've outgrown and forecasts drift
from reality. This playbook is a recurring, evidence-based cleanup and forecast.

## Cadence
Run weekly (or before any forecast the CEO/finance role needs).

## Workflow
1. **Pull the pipeline.** `crm_list_deals`. For each open deal, check last activity via
   `crm_contact_timeline`.
2. **Stage-test every deal.** A deal may only occupy a stage if its exit criteria are met:
   - *Qualified* — fit + explicit need confirmed.
   - *Discovery done* — quantified pain + decision process known.
   - *Proposal* — pricing sent, champion engaged.
   - *Commit* — verbal yes + procurement/legal path clear.
   If criteria aren't met, `update_deal` to the true stage (usually backwards — that's healthy).
3. **Flag stalled deals.** No activity in 14 days → either `schedule_followup` with a
   specific re-engagement reason, or move to the `lost-deal-winback` path / mark lost.
4. **Forecast honestly.** Sum expected value by stage-weighted probability. State the
   number with its assumptions; never round pipeline up to hit a target.
5. **Report.** `record_metric` for pipeline value, weighted forecast, stage conversion, and
   stalled count. If finance/CEO needs it, `create_report` (kind `research_report` or the
   nearest report kind) with the forecast and the top 3 at-risk deals.

## Decision framework — kill vs. keep
Keep a deal only if you can name (a) the next step, (b) its date, and (c) the champion. If
any is missing, it's not a forecastable deal — nurture or close it.

## Definition of done
- Every open deal sits in a stage whose exit criteria it actually meets.
- Stalled deals have a dated next step or are closed.
- A weighted forecast with stated assumptions is recorded.

## Common failure modes
- **Happy-ears staging.** A good call is not a stage change; exit criteria are.
- **Zombie deals.** Deals kept alive for morale distort the forecast — close them.
- **Sandbagging or inflating.** Both destroy trust in the number; report what's real.
