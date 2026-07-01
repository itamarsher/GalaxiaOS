---
name: pricing-model-financials
title: Pricing Model Financials
description: Build and stress-test the financial model behind a pricing decision so price aligns with value and margin.
roles: finance, growth, ceo
---
# Pricing Model Financials

Price is where value meets margin. This playbook builds the financial model behind a pricing
decision so the number is defensible on both — not set by gut or copied from a competitor.

## Workflow
1. **Ground in cost and value.** Compute the cost to serve (`unit-economics-analysis`) as the floor
   and the value delivered to the customer as the ceiling. Price lives between; below cost bleeds,
   above value doesn't sell.
2. **Model the packaging.** Tiers, usage, seats, or flat — model each on real segment behavior. The
   structure should map to how customers get and perceive value (`jobs-to-be-done-analysis`).
3. **Project margin at each price.** For candidate prices, model contribution margin and blended
   economics across the expected customer mix (`read_financials`). A price that wins volume but
   erodes margin can be a loss.
4. **Stress-test elasticity.** Model revenue under different conversion assumptions at each price.
   Identify where a higher price's better margin outweighs lower conversion (and vice versa).
5. **Check against reality.** Benchmark competitor pricing (`pricing-benchmark-research`) for
   context — but anchor on your cost and value, not their number.
6. **Recommend and record.** `write_memory` (type `result`) the recommended price with its margin
   and assumptions; `request_decision` from CEO/finance; validate live via `pricing-experiment`.

## Decision framework — value-based, margin-guarded
Price to the value delivered, floored by cost-to-serve and guarded by target margin. Cost-plus
leaves value on the table; competitor-copying ignores your economics. Model both, decide on value.

## Definition of done
- Cost floor and value ceiling established; packaging modeled on real behavior.
- Margin and elasticity projected across prices; recommendation recorded and routed for decision.

## Common failure modes
- **Cost-plus pricing.** Ignores the value customers actually get; leaves money on the table.
- **Competitor-copying.** Their costs and value aren't yours.
- **Volume over margin.** A cheaper price that loses money per unit isn't a win.
