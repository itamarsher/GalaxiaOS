---
name: industry-trend-scan
title: Industry Trend Scan
description: Systematically monitor the forces shaping the market so the company sees change before it hits.
roles: research, ceo
---
# Industry Trend Scan

Companies get blindsided by trends they could have seen. This playbook is a structured scan of
the forces shaping the market, producing early signal the fleet can act on.

## Workflow
1. **Frame what matters.** Which trends could change our strategy — technology, regulation, buyer
   behavior, competition, economics? Scan for decision-relevant change, not interesting trivia.
2. **Scan broad, real sources.** `web_search` across news, analyst notes, competitor moves,
   funding activity, and regulatory signals. Capture sources — never assert a trend without evidence.
3. **Separate signal from noise.** Distinguish a durable shift from a fad. Ask: is this accelerating,
   who's investing behind it, and does it change customer behavior? One headline is not a trend.
4. **Assess impact and timing.** For each real trend: does it help or threaten us, and on what
   horizon (now / next year / later)? An accurate trend on the wrong timescale misleads planning.
5. **Turn into implications.** `write_memory` (type `learning`) each trend with its "so what for us."
   A trend with no implication for our decisions isn't worth tracking.
6. **Report and route.** `create_report` (kind `research_report`) with the top trends, implications,
   and recommended responses; `request_decision` on anything strategy-altering.

## Decision framework — durable shift vs. fad
Weight trends by evidence of durability and investment behind them. Chasing every fad is as
dangerous as missing a real shift; the scan's job is to tell them apart.

## Definition of done
- Decision-relevant trends scanned from sourced evidence; signal separated from noise.
- Impact and timing assessed; implications and recommended responses reported.

## Common failure modes
- **Trivia collection.** Interesting ≠ decision-relevant.
- **Fad-chasing.** Reacting to hype that fades wastes focus and budget.
- **Trends without "so what."** If it doesn't change a decision, it's noise.
