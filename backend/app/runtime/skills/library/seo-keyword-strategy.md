---
name: seo-keyword-strategy
title: SEO Keyword Strategy
description: Use when planning or auditing which keywords to target and how to map them to content that can rank and be measured.
roles: growth, research
---
# SEO Keyword Strategy

Ranking for the wrong keywords is invisible work. This playbook picks keywords by buyer
intent and realistic **winnability**, then locks each one to a content task and a measurable outcome.

## Workflow
1. **Seed from real demand.** `web_search` around the problem you solve, competitor pages,
   and "how do I…" queries. Capture candidates with volume and intent signals — no invented numbers;
   mark anything unsourced as uncertain.
2. **Classify by intent:** informational, comparison, or transactional. Transactional and
   comparison keywords convert; informational builds top-of-funnel authority.
3. **Score winnability.** For each keyword, judge difficulty vs. your domain authority. A young
   site wins long-tail specific terms first — ten long-tail wins beat one unwinnable head term.
4. **Prioritize.** Rank by (intent value × winnability). Pick the top cluster to act on now.
5. **Map to content and instrument.** Assign each chosen keyword to a page or pillar;
   `dispatch_task` to `blog-post-production` with target keyword and intent attached.
   Immediately `record_metric` for baseline ranking/traffic so progress is measurable from day one.
6. **Record what works.** After each cycle, `write_memory` (type `learning`) noting which keyword
   types actually drove traffic or conversions — close the loop or the strategy drifts.

## Decision framework — head vs. long-tail
Prefer specific long-tail terms with clear intent early. Move toward broader terms only as
domain authority grows and you have data showing which intent types convert.

## Definition of done
- Keywords classified by intent, scored for winnability, and prioritized.
- Top cluster mapped to specific content tasks with target terms attached.
- Baseline metrics recorded; at least one `learning` memory queued for the next cycle.

## Common failure modes
- **Chasing volume.** High-volume head terms you can't rank for return nothing.
- **Invented metrics.** If you can't source volume/difficulty, mark it uncertain — never fabricate.
- **Keywords with no page.** A strategy not mapped to content is just a list.
- **No instrumentation.** Skipping `record_metric` means you can never prove or improve results.
