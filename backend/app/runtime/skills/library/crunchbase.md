---
name: crunchbase
title: Crunchbase
description: Research a company, funding round, investor, or founder — or build a market map — using Crunchbase's private-company dataset.
roles: research
---
# Crunchbase

Crunchbase is the go-to dataset for private-company intelligence — funding rounds, investors, acquisitions,
and leadership across millions of companies. Its numbers are **estimates and partly self-reported, never
ground truth**. The ABOS-adapted principle: **connect it as a tool first, never assume it's wired**, then
treat every figure as a lead to verify, not a fact to state.

## Connect before you research
1. **Find the tool.** `discover_tools` with query `crunchbase`; it exposes as `mcp__crunchbase__*` once the
   founder has connected it. Load what you need with `use_tool`.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Crunchbase in
   Settings (MCP server or API key). Never invent a funding figure, investor, or profile — a fabricated data
   point poisons every downstream decision.
3. **Egress.** Queries send company/target names to a third party; `check_compliance` if the research subject
   is sensitive.

## Research with the caveats built in
4. **Use advanced search to build the map.** Filter by industry, geography, funding stage, and last-funding
   date to assemble a market map or comp set — that structured query is the value, not a single lookup.
5. **Treat every field as an estimate.** Employee counts, revenue ranges, and stages are often self-reported
   and can be months stale; coverage skews US-centric and thin outside it. Cross-check anything decision-
   critical (a round, a valuation, a headcount) against a second source before acting on it.
6. **Cite freshness, never launder into fact.** When you report a figure, carry its source and as-of date
   ("per Crunchbase, last updated Q1 2026"). Present ranges as ranges. Never round an estimate into a precise
   claim.

## File the deliverable and record it
7. **File findings + record.** `save_file` the market map / comp set (category `artifact`) with sources and
   dates in the description; `write_memory` (type `result` or `learning`) the key findings and their caveats;
   `record_metric` only for figures you have verified.

## Definition of done
- Crunchbase confirmed connected (or escalated, never faked); egress checked.
- Advanced-search query built; decision-critical figures cross-checked against a second source.
- Findings filed with sources and as-of dates; nothing presented as exact that is an estimate.

## Common failure modes
- **Estimate laundered as fact.** Stating a self-reported employee count or valuation as precise truth.
- **Phantom data.** Inventing a funding round or investor when Crunchbase was never connected — escalate.
- **Stale signal.** Acting on a quarters-old figure without noting or checking its freshness.
