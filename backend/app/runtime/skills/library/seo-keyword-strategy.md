---
name: seo-keyword-strategy
title: SEO Keyword Strategy
description: Use when deciding which keywords to target, how to prioritize them by winnability and intent, and how to wire each to a content task and a measurable baseline — so the strategy produces trackable outcomes, not just a list.
roles: growth, research
---
# SEO Keyword Strategy

Ranking for the wrong keywords is invisible work. This playbook picks keywords by buyer
intent and realistic **winnability**, then locks each one to a content task and a measurable outcome.
The leading principle: **instrument before you move on** — no keyword leaves this workflow without a
baseline metric attached.

## Workflow

1. **Seed from real demand.** `web_search` around the problem you solve, competitor pages,
   and "how do I…" queries. Capture candidates with volume and intent signals — no invented numbers;
   mark anything unsourced as uncertain.

2. **Classify by intent:** informational, comparison, or transactional. Transactional and
   comparison keywords convert; informational builds top-of-funnel authority.

3. **Score winnability.** For each keyword, judge difficulty vs. your domain authority. A young
   site wins long-tail specific terms first — ten long-tail wins beat one unwinnable head term.

4. **Prioritize.** Rank by (intent value × winnability). Pick the top cluster to act on now.

5. **Map to content.** Assign each chosen keyword to a page or pillar; `dispatch_task` to
   `blog-post-production` with the target keyword and intent attached.

6. **Instrument before you move on.** `record_metric` for baseline ranking and traffic for
   every keyword in the chosen cluster — do this in the same session, not later. A keyword without
   a baseline cannot be proved or improved.

7. **Close the loop.** After each cycle, `write_memory` (type `learning`) noting which keyword
   types drove traffic or conversions. Without this step the strategy drifts.

## Decision framework — head vs. long-tail

Prefer specific long-tail terms with clear intent early. Move toward broader terms only as
domain authority grows and you have data showing which intent types convert.

## Definition of done

- Keywords classified by intent, scored for winnability, and prioritized.
- Top cluster mapped to specific content tasks with target terms attached.
- `record_metric` called for every chosen keyword (baseline ranking/traffic) in this session.
- At least one `learning` memory queued for the next cycle.

## Common failure modes

- **Chasing volume.** High-volume head terms you can't rank for return nothing.
- **Invented metrics.** If you can't source volume/difficulty, mark it uncertain — never fabricate.
- **Keywords with no page.** A strategy not mapped to content is just a list.
- **Skipping instrumentation.** The single most common failure: `record_metric` deferred and never done. **Instrument before you move on.**
