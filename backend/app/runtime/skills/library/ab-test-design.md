---
name: ab-test-design
title: A/B Test Design
description: Design an experiment with a real hypothesis, adequate sample, and honest reading so results mean something.
roles: product, data, growth
---
# A/B Test Design

A badly designed A/B test produces confident nonsense. This playbook enforces the discipline —
hypothesis, sample, single variable, honest stopping — so a result you can trust.

## Workflow
1. **Write a falsifiable hypothesis.** "Variant B will increase [primary metric] by [amount]
   because [reason]." Pick ONE primary metric before running. `write_memory` (type `experiment`).
2. **Change one variable.** Multiple simultaneous changes make results uninterpretable. Isolate.
3. **Size the sample.** Estimate the sample/duration needed to detect the expected effect at a
   reasonable confidence, given baseline rate (`read_metrics`). Underpowered tests waste traffic
   and mislead. If you can't reach the sample, don't run it — decide by judgment and say so.
4. **Guard against peeking.** Decide the stopping point in advance. Reading results early and
   stopping when it "looks good" manufactures false positives.
5. **Run and measure.** Split randomly; `record_metric` for the primary metric and key guardrail
   metrics (a variant that lifts clicks but tanks revenue is a loss — see `pricing-experiment`).
6. **Read honestly and decide.** `write_memory` (type `result`): did it hit significance? A flat
   or negative result is a real finding. Ship winners; `update_company_playbook` with the learning.

## Decision framework — ship, kill, or inconclusive
Only ship on a clear, significant win on the primary metric with guardrails intact. "Looks
slightly better" from an underpowered test is not a result — call it inconclusive.

## Definition of done
- One hypothesis, one variable, pre-committed sample and stopping rule.
- Primary + guardrail metrics measured; honest significance-based decision recorded.

## Common failure modes
- **Peeking and early-stopping.** The most common way to fabricate a false win.
- **Underpowered tests.** Too little traffic → noise mistaken for signal.
- **Ignoring guardrails.** A local win that hurts revenue/retention is a net loss.
