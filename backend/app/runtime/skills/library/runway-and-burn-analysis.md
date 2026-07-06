---
name: runway-and-burn-analysis
title: Runway & Burn Analysis
description: Calculate real burn and runway from measured spend, and surface the date the company must act by.
roles: finance, ceo, auditor
---
# Runway & Burn Analysis

Runway is the single most important survival number. This playbook computes it honestly from
measured spend so the fleet always knows how long it has and when it must change course.

## Workflow
1. **Measure real burn.** `read_financials` for actual spend over recent periods — including LLM
   token cost and external charges (both flow through the CostMeter). Use trailing actuals, not
   budget assumptions.
2. **Separate gross vs. net burn.** Net burn (spend minus revenue) drives runway; gross burn
   matters if revenue is volatile. Compute both.
3. **Compute runway.** Cash ÷ net monthly burn = months of runway. State the exact "zero date."
   If burn is rising or lumpy, use a conservative trend, not the best recent month.
4. **Stress-test it.** What happens to runway if revenue slips 20% or a planned cost lands? Model
   the downside (`budget-planning-and-forecast` scenarios).
5. **Set trigger dates.** Identify the date by which the company must raise, cut, or hit a revenue
   milestone to stay solvent. This is the number that should drive strategy.
6. **Report clearly.** `record_metric` for burn and runway; `create_report` (kind `financial_report`)
   or feed the `weekly-investor-update`. `request_decision` / `send_notification` if runway crosses
   a danger threshold — silence here is negligence.

## Decision framework — the trigger, not the average
Plan around the conservative zero-date, not the optimistic one. It's better to act a month early
than a day late; running out of runway is terminal and irreversible.

## Definition of done
- Burn from trailing actuals (LLM + external); gross and net computed; exact zero-date stated.
- Downside stress-tested; trigger dates set; danger thresholds escalated.

## Common failure modes
- **Best-month burn.** Optimistic burn hides how little runway remains.
- **Ignoring token/external spend.** Both are real burn through the CostMeter.
- **Quiet danger.** Crossing a runway threshold must trigger a decision, not a footnote.
