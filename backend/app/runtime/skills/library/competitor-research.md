---
name: competitor-research
title: Competitor & Market Research
description: Produce a grounded competitive landscape from real sources, not guesses.
roles: research, ceo, product
---
# Competitor & Market Research

Turn an open question ("who else does this and how do we win?") into a grounded,
cited landscape the company can act on.

## 1. Frame the question
- Restate exactly what decision this research will inform (pricing, positioning,
  feature priority). Research with no decision attached is wasted budget.

## 2. Gather real evidence
- Use `web_search` to find competitors, pricing pages, reviews, and market size
  data. If web search is unsupported, `request_capability` rather than inventing
  facts — never fabricate competitors, numbers, or quotes.
- Capture each useful finding as a `write_memory` of type `result` with the source.

## 3. Structure the landscape
- For each competitor: who they target, their pricing, their core wedge, and the
  gap they leave open.
- Identify the 1–2 gaps most aligned with our mission — these are candidate wedges.

## 4. Synthesize and hand off
- `write_memory` a `learning` capturing the sharpest insight and its implication.
- If the founder should see it, produce a `create_report` (kind `research_report`)
  summarizing the landscape, the recommended wedge, and the open risks.
- `report_result` with the headline recommendation.
