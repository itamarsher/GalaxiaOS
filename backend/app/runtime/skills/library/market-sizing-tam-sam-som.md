---
name: market-sizing-tam-sam-som
title: Market Sizing (TAM/SAM/SOM)
description: Estimate addressable market with a transparent, defensible method — not a top-down guess.
roles: research, ceo, finance
---
# Market Sizing (TAM/SAM/SOM)

Market sizing informs strategy and fundraising, so it must be defensible. This playbook builds a
transparent estimate from real inputs — showing the math, not asserting a big number.

## Workflow
1. **Anchor to the decision.** Why size the market — fundraising, prioritization, go/no-go? The
   decision sets the precision needed. `write_memory` (type `experiment`) the question.
2. **Build bottom-up first.** (# of target customers) × (realistic annual value each). Source both
   from real data (`web_search`, industry reports, your own pricing). Bottom-up resists the fantasy
   of top-down "1% of a huge market."
3. **Layer the three rings:**
   - *TAM* — everyone who has the problem.
   - *SAM* — those you can actually serve (geography, segment, product fit).
   - *SOM* — what you can realistically capture in the near term.
   Each is a subset with a stated reason for the narrowing.
4. **Show every assumption.** Each number has a source or a stated estimate. A market size with
   hidden assumptions is worthless; one with visible math can be debated and trusted.
5. **Cross-check top-down.** Compare with analyst market figures for sanity — if bottom-up and
   top-down diverge wildly, find out why before trusting either.
6. **Report.** `create_report` (kind `research_report`) with the estimate, the method, and the
   assumptions; `write_memory` (type `result`) the SOM used for planning.

## Decision framework — bottom-up over top-down
Trust bottom-up math you can defend over top-down percentages of huge numbers. "1% of a $50B
market" is a wish; "5,000 reachable customers × $6k = $30M SAM" is an argument.

## Definition of done
- Sizing tied to a decision; bottom-up TAM/SAM/SOM with each narrowing justified.
- Every assumption sourced or labeled; top-down sanity check done; method reported.

## Common failure modes
- **Top-down hand-waving.** "1% of a giant market" persuades no serious investor.
- **Hidden assumptions.** Unshowable math is untrustworthy math.
- **No SAM/SOM narrowing.** TAM alone overstates what you can actually address.
