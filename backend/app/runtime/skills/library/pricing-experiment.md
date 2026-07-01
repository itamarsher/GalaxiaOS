---
name: pricing-experiment
title: Pricing Experiment
description: Test a pricing or packaging change safely, measuring impact on conversion and revenue, not just clicks.
roles: growth, finance, ceo
---
# Pricing Experiment

Pricing is the highest-leverage and highest-risk lever. This playbook tests a change with a
clear hypothesis and guardrails so you learn without torching revenue or trust.

## Workflow
1. **State the hypothesis.** "Changing price/packaging from A to B will improve [conversion /
   ARPU / revenue] because [reason]." One variable. `write_memory` (type `experiment`).
2. **Check the blast radius.** Pricing touches finance and existing customers. `request_decision`
   from CEO/finance before any live change — never change price unilaterally. Grandfather existing
   customers unless explicitly decided otherwise.
3. **Pick the measurement.** Decide the primary metric (revenue per visitor is safer than raw
   conversion — a price cut can raise conversion and lower revenue). Set the sample/time needed.
4. **Run it isolated.** Apply to a new segment or time window so you can attribute the effect.
   Keep the rest of the funnel constant.
5. **Read revenue, not vanity.** `read_financials` / `read_metrics` and `record_metric` for
   conversion AND revenue per visitor AND refund/churn signal.
6. **Decide and document.** `write_memory` (type `result`) the effect on revenue; if adopting,
   `update_company_playbook` with the new price and `request_decision` to make it default.

## Decision framework — the trap
A change that lifts sign-ups but lowers revenue-per-visitor is a loss dressed as a win. Always
judge on revenue and downstream retention, not top-of-funnel conversion alone.

## Definition of done
- Hypothesis + one variable; CEO/finance sign-off; existing customers handled explicitly.
- Judged on revenue and retention, not conversion alone; result recorded.

## Common failure modes
- **Unilateral price changes.** Finance and existing customers must be in the loop.
- **Optimizing conversion, losing revenue.** Measure the money.
- **Ignoring churn/refunds.** A price that converts but churns isn't a win.
