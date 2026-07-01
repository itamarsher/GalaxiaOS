---
name: seo-keyword-strategy
title: SEO Keyword Strategy
description: Choose keywords by intent and winnability, then map them to content that can actually rank.
roles: growth, research
---
# SEO Keyword Strategy

Ranking for the wrong keywords is invisible work. This playbook picks keywords by buyer
intent and realistic winnability, then maps them to a content plan.

## Workflow
1. **Seed from real demand.** `web_search` around the problem you solve, competitor pages,
   and "how do I…" queries. Capture candidates with volume and intent signals — no invented numbers.
2. **Classify by intent:** informational, comparison, or transactional. Transactional and
   comparison keywords convert; informational builds top-of-funnel and links.
3. **Score winnability.** For each keyword, judge difficulty vs. our authority. A young
   company wins long-tail, specific terms first, not head terms owned by incumbents.
4. **Prioritize.** Rank by (intent value × winnability). Pick the top cluster to start.
5. **Map to content.** Assign each chosen keyword to a pillar/page in the `content-marketing-calendar`;
   `dispatch_task` to `blog-post-production` with the target keyword and intent.
6. **Measure and iterate.** `record_metric` for rankings/traffic per target; `write_memory`
   (type `learning`) which keyword types actually convert for us.

## Decision framework — head vs. long-tail
Prefer specific long-tail terms with clear intent early. Ten long-tail wins beat one
unwinnable head term. Move up-funnel as domain authority grows.

## Definition of done
- Keywords classified by intent, scored for winnability, and prioritized.
- Top cluster mapped to specific content tasks with target terms attached.

## Common failure modes
- **Chasing volume.** High-volume head terms you can't rank for return nothing.
- **Invented metrics.** If you can't source volume/difficulty, mark it uncertain.
- **Keywords with no page.** A strategy that isn't mapped to content is just a list.
