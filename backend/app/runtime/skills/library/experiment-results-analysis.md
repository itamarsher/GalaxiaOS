---
name: experiment-results-analysis
title: Experiment Results Analysis
description: Analyze A/B and experiment results rigorously so the fleet ships real wins, not noise.
roles: data, product, growth
---
# Experiment Results Analysis

The analysis stage is where good experiments get ruined by wishful reading. This playbook analyzes
results rigorously so decisions rest on real effects, not noise or bias.

## Workflow
1. **Recall the pre-registered plan.** Pull the hypothesis, primary metric, sample target, and stopping
   rule from the experiment's `write_memory` (`ab-test-design`). Analyzing against a pre-set plan is what
   prevents fishing for a story.
2. **Verify validity first.** Was the sample reached? Was assignment truly random and balanced? Did
   anything contaminate the test (overlapping changes, seasonality)? An invalid test has no result to read.
3. **Read the primary metric with uncertainty.** `read_metrics` the variant vs. control on the ONE primary
   metric. Report the effect size AND its confidence — a point estimate without a range invites over-reading.
4. **Check guardrail metrics.** Confirm the variant didn't win the primary metric by harming another
   (revenue, retention, quality). A local win that hurts a guardrail is a net loss (`pricing-experiment`).
5. **Beware the traps.** Don't cherry-pick a secondary metric that happened to move; don't slice into
   subgroups until one looks significant. These manufacture false wins. Flag any post-hoc finding as a
   hypothesis, not a result.
6. **Decide and record.** `write_memory` (type `result`): ship, kill, or inconclusive, with the evidence.
   Ship only clear, significant wins with guardrails intact; `update_company_playbook` with the learning.

## Decision framework — inconclusive is a valid answer
If the effect isn't clear and significant on the pre-registered primary metric, the honest result is
"inconclusive" — not the best-looking secondary metric. Calling noise a win is how bad features ship.

## Definition of done
- Analyzed against the pre-registered plan; validity verified; primary metric read with uncertainty.
- Guardrails checked; post-hoc findings labeled as hypotheses; explicit ship/kill/inconclusive decision recorded.

## Common failure modes
- **Metric fishing.** Hunting for any metric or subgroup that moved to declare a win.
- **Ignoring uncertainty.** Reading a point estimate from an underpowered test as fact.
- **Guardrail blindness.** Shipping a primary-metric win that quietly hurt revenue/retention.
