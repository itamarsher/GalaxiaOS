---
name: seo-keyword-strategy
title: SEO Keyword Strategy
description: Use when picking, scoring, and assigning keywords to content tasks — runs the full select-score-map loop and ends only when every chosen keyword has a recorded baseline metric.
roles: growth, research
---
# SEO Keyword Strategy

Ranking for the wrong keywords is invisible work. The leading principle: **instrument before you move on** — no keyword leaves this session without a baseline metric attached.

## Workflow

1. **Seed from real demand.** `web_search` the problem you solve, competitor pages, and "how do I…" queries. Capture candidates with volume and intent signals. Mark anything unsourced as uncertain — never fabricate numbers.

2. **Classify by intent:** informational, comparison, or transactional. Transactional and comparison keywords convert; informational builds top-of-funnel authority.

3. **Score winnability.** Judge difficulty vs. your domain authority. Ten long-tail wins beat one unwinnable head term.

4. **Prioritize.** Rank by (intent value × winnability). Pick the top cluster to act on now.

5. **Map to content.** Assign each chosen keyword to a page or pillar; `dispatch_task` to `blog-post-production` with the target keyword and intent attached.

6. **Instrument before you move on.** Call `record_metric` for baseline ranking and traffic for **every keyword in the chosen cluster — right now, before closing this session.** Do not mark any keyword done until its baseline is recorded. This is the step most often skipped; do not skip it.

7. **Close the loop.** `write_memory` (type `learning`) noting which keyword types drove traffic or conversions.

## Definition of done

- Keywords classified by intent, scored for winnability, and prioritized.
- Top cluster mapped to specific content tasks with target terms attached.
- `record_metric` called for **every** chosen keyword (baseline ranking/traffic) in this session.
- At least one `learning` memory written before session closes.

## Common failure modes

- **Skipping instrumentation.** `record_metric` deferred and never done. **Instrument before you move on.** No baseline = no proof, no improvement.
- **Chasing volume.** High-volume head terms you can't rank for return nothing.
- **Invented metrics.** Mark uncertain if unsourced — never fabricate.
- **Keywords with no page.** A strategy not mapped to content is just a list.
