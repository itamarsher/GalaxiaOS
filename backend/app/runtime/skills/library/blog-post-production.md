---
name: blog-post-production
title: Blog Post Production
description: Produce a single high-quality, on-intent blog post from brief to published, grounded in real facts.
roles: growth, research
---
# Blog Post Production

This playbook takes one content slot from brief to published — useful, accurate, and built
to rank and convert, not to pad a calendar.

## Workflow
1. **Read the brief.** Target keyword, search intent, pillar, and the one action the reader
   should take. If missing, get them from `seo-keyword-strategy` / `content-marketing-calendar`.
2. **Research for accuracy.** `web_search` for current facts, stats, and examples; capture
   sources. Never invent statistics, quotes, or study results — cite or cut.
3. **Outline for the intent.** Structure to answer the query fast (answer-first for informational,
   comparison table for comparison, clear CTA for transactional).
4. **Draft.** `draft_document` in the company voice (pull it from `get_company_playbook`).
   Original angle, concrete examples, no fluff. Add a visual with `generate_image` if it aids clarity.
5. **Fact- and compliance-check.** Verify every claim against a source; `check_compliance` if
   the topic is regulated (health, finance, legal claims).
6. **Publish and distribute.** `publish_content`; then `schedule_social_post` for distribution.
   `record_metric` baseline for later tracking.

## Quality bar
Would a knowledgeable reader learn something and trust us more? If it only restates what's
already on page one of search, rewrite it or don't ship it.

## Definition of done
- On-intent structure, every stat sourced, company voice, one clear CTA.
- Published and queued for distribution; baseline metric recorded.

## Common failure modes
- **AI-slop restating the obvious.** Adds no value and can hurt rankings.
- **Fabricated stats.** One invented number destroys the whole piece's credibility.
- **Publish-and-forget.** Distribution is half the work.
