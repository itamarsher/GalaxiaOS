---
name: similarweb
title: SimilarWeb
description: Estimate a website's traffic, engagement, traffic sources, or audience — or benchmark competitors — using SimilarWeb.
roles: research, growth
---
# SimilarWeb

SimilarWeb estimates website traffic, engagement, sources, and audience for almost any domain — built from
clickstream panels and modeled data, so its numbers are **directional estimates, never measured truth**. The
ABOS-adapted principle: **connect it as a tool first, never assume it's wired**, then read the figures as
relative signal for comparison, not absolute fact.

## Connect before you pull data
1. **Find the tool.** `discover_tools` with query `similarweb`; it exposes as `mcp__similarweb__*` once the
   founder has connected it. Load what you need with `use_tool`.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect SimilarWeb in
   Settings (MCP server or API key). Never invent a visit count or traffic-source split — a fabricated metric
   sends the growth plan the wrong way.
3. **Egress.** Domain queries go to a third party; `check_compliance` if the target list is sensitive.

## Read the estimates honestly
4. **Benchmark relatively, not absolutely.** SimilarWeb's strength is *comparison* — you vs. competitors on
   visits, share, and channel mix. Trust the ranking and trend more than the exact number.
5. **Mind the error margins.** Estimates are most reliable for larger sites; below ~5K monthly visits they get
   noisy, and tools can diverge 50%+ on the same domain. For low-traffic or niche targets, widen your
   confidence and say so.
6. **Use the full picture, then cross-reference.** Pull traffic sources (direct/search/referral/social),
   engagement (visit duration, pages/visit, bounce), and audience — but for anything you'll bet budget on,
   corroborate with a second tool rather than a single estimate.

## File the deliverable and record it
7. **File findings + record.** `save_file` the benchmark / traffic report (category `artifact`) with the
   as-of date and "estimated" flagged in the description; `write_memory` (type `result` or `learning`) the
   comparative findings and their confidence; `record_metric` only for figures used as directional, labelled
   estimates.

## Definition of done
- SimilarWeb confirmed connected (or escalated, never faked); egress checked.
- Findings framed as relative benchmarks with error margins noted; low-traffic caveats stated.
- Report filed with as-of date and estimate label; nothing presented as measured truth.

## Common failure modes
- **Estimate as measurement.** Reporting a modeled visit count as the competitor's real number.
- **Small-site overreach.** Trusting precise figures for a sub-5K-visit domain where the margin is huge.
- **Phantom metric.** Inventing traffic data when SimilarWeb was never connected — escalate instead.
