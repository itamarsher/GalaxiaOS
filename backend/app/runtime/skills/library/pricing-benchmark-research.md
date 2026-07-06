---
name: pricing-benchmark-research
title: Pricing Benchmark Research
description: Map how comparable products are priced and packaged to inform (not dictate) our pricing.
roles: research, finance, growth
---
# Pricing Benchmark Research

Knowing how the market prices comparable value is essential context for a pricing decision. This
playbook gathers it rigorously — as input to our own value/margin math, not a number to copy.

## Workflow
1. **Define comparables.** Identify products that solve a similar job for a similar buyer — not just
   named competitors. The right comparison is by value delivered, not category label.
2. **Gather real pricing.** `web_search` pricing pages, plans, and public deal data. Capture the
   full structure: model (seat/usage/flat), tiers, what's gated, and list vs. typical actual price.
   Never invent a competitor's price.
3. **Normalize for comparison.** Different packaging hides real price differences. Express each on a
   common basis (e.g. price per unit of the value the buyer cares about) so comparisons are fair.
4. **Map the value-price landscape.** Plot who's premium, who's budget, and where gaps exist. A gap
   between a cheap-limited tier and an expensive-full one is a positioning opportunity.
5. **Extract implications, not a copy.** `write_memory` (type `learning`) how the market frames and
   tiers value. Feed it into `pricing-model-financials` — anchor on our cost and value, using this as context.
6. **Report.** `create_report` (kind `research_report`) with the landscape and the pricing-strategy
   options it suggests.

## Decision framework — context, not instruction
Use benchmarks to understand market expectations and packaging norms, then price on your own value
and margin. Copying a competitor's price copies their cost structure and mistakes too.

## Definition of done
- Comparables chosen by value/job; real pricing captured and normalized to a common basis.
- Value-price landscape mapped with gaps; implications fed to the pricing model.

## Common failure modes
- **Category-only comparables.** The real competitor may be a spreadsheet, not a named rival.
- **Un-normalized comparison.** Different packaging makes raw prices misleading.
- **Copy-the-competitor.** Their economics and positioning aren't yours.
