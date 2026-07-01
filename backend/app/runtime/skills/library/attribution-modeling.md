---
name: attribution-modeling
title: Attribution Modeling
description: Attribute outcomes to channels honestly so budget flows to what actually drives results.
roles: data, growth, finance
---
# Attribution Modeling

Attribution decides where the budget goes, so getting it wrong wastes money on the wrong channels. This
playbook attributes outcomes as honestly as the data allows — and is upfront about its limits.

## Workflow
1. **Frame the decision.** Attribution exists to allocate budget (`paid-ads-campaign-launch`,
   `unit-economics-analysis`). Model to that decision — perfect attribution is impossible; useful-enough is the goal.
2. **Capture the real touchpoints.** `crm_contact_timeline` and tracked links/sources (`log_lead`) for how
   customers actually found and converted. Missing touchpoints bias attribution toward what's measured.
3. **Choose a model deliberately.** First-touch (credits discovery), last-touch (credits closing), or
   multi-touch (spreads credit). Each tells a different story; state which you're using and why. Don't let a
   default tool choice silently decide strategy.
4. **Acknowledge the limits.** Some influence is unmeasurable (word of mouth, brand, dark social). Don't
   over-credit trackable channels just because they're trackable — that's how brand and referral get starved.
5. **Cross-check with holdouts.** Where possible, validate with a real test (a channel paused, a geo holdout)
   — incrementality beats correlation. `write_memory` (type `experiment`) the check.
6. **Recommend allocation.** `write_memory` (type `result`) each channel's honest contribution and CAC;
   `record_metric`; recommend shifts to finance/growth with the model's caveats stated.

## Decision framework — incrementality over credit
The real question isn't 'which touch gets credit' but 'what happens if we cut this channel.' Where you can,
trust holdout/incrementality tests over any attribution model's neat story.

## Definition of done
- Modeled to a budget decision; real touchpoints captured; model chosen deliberately with rationale.
- Unmeasurable influence acknowledged; validated with holdouts where possible; allocation recommended with caveats.

## Common failure modes
- **Trackable-channel bias.** Over-crediting measurable channels and starving brand/referral.
- **Silent default model.** Letting a tool's default attribution quietly set strategy.
- **Correlation as causation.** Trusting the model's story over an incrementality test.
