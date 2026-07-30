---
name: seo-keyword-strategy
title: SEO Keyword Strategy
description: Use when you need to pick, prioritize, and assign keywords to content tasks — and must lock each keyword to a measurable baseline before the session ends.
roles: growth, research
---
# SEO Keyword Strategy

Ranking for the wrong keywords is invisible work. This playbook picks keywords by buyer
intent and realistic **winnability**, then locks each one to a content task and a measurable outcome.
The leading principle: **instrument before you move on** — no keyword leaves this workflow without a
baseline metric attached.

## Workflow

1. **Seed from real demand.** `web_search` around the problem you solve, competitor pages,
   and "how do I…" queries. Capture candidates with volume and intent signals. Mark anything
   unsourced as uncertain — never fabricate numbers.

2. **Classify by intent:** informational, comparison, or transactional. Transactional and
   comparison keywords convert; informational builds top-of-funnel authority.

3. **Score winnability.** Judge difficulty vs. your domain authority. A young site wins
   long-tail specific terms first — ten long-tail wins beat one unwinnable head term.

4. **Prioritize.** Rank by (intent value × winnability). Pick the top cluster to act on now.

5. **Map to content.** Assign each chosen keyword to a page or pillar; `dispatch_task` to
   `blog-post-production` with the target keyword and intent attached.

6. **Instrument before you move on.** Call `record_metric` for baseline ranking and traffic for
   every keyword in the chosen cluster — **in this session, not later**. This step is not optional:
   a keyword without a baseline cannot be proved or improved. Do not close the session until
   `record_metric` has been called for each keyword in the cluster.

7. **Close the loop.** `write_memory` (type `learning`) noting which keyword types drove
   traffic or conversions. Without this step the strategy drifts.

## Decision framework — head vs. long-tail

Prefer specific long-tail terms with clear intent early. Move toward broader terms only as
domain authority grows and data shows which intent types convert.

## Definition of done

- Keywords classified by intent, scored for winnability, and prioritized.
- Top cluster mapped to specific content tasks with target terms attached.
- `record_metric` called for **every** chosen keyword (baseline ranking/traffic) in this session.
- At least one `learning` memory written before session closes.

## Common failure modes

- **Skipping instrumentation.** The single most common failure: `record_metric` deferred and never done. **Instrument before you move on.** Do not treat any keyword as "done" until its baseline is recorded.
- **Chasing volume.** High-volume head terms you can't rank for return nothing.
- **Invented metrics.** If you can't source volume/difficulty, mark it uncertain — never fabricate.
- **Keywords with no page.** A strategy not mapped to content is just a list.
