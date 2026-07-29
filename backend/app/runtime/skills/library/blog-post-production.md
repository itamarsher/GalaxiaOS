---
name: blog-post-production
title: Blog Post Production
description: Use when a content brief (or enough inputs to reconstruct one) is ready and a single blog post must be drafted, fact-checked, published, and baselined with a metric — in one pass.
roles: growth, research
---
# Blog Post Production

One job: take a content slot from brief to **published-and-baselined**. Every step that doesn't serve that job is cut.

## Workflow

1. **Lock the brief.** Confirm target keyword, search intent, pillar, and the one action the reader should take. Pull missing inputs from `seo-keyword-strategy` or `content-marketing-calendar` before going further.

2. **Source before you write.** `web_search` for current facts, stats, and examples; log every URL. **Never invent a statistic, quote, or study result — cite it or cut it.**

3. **Outline to the intent.** Answer-first for informational; comparison table for comparison; prominent CTA for transactional. Structure serves the query, not word count.

4. **Draft in company voice.** `draft_document` using voice guidelines from `get_company_playbook`. One original angle, concrete examples, no restatements of page-one search results. Add a visual via `generate_image` only if it genuinely aids comprehension.

5. **Check before you ship.** Verify every claim against a logged source. Run `check_compliance` for regulated topics (health, finance, legal).

6. **Publish, distribute, and baseline — in that order.** `publish_content` → `schedule_social_post` → **`record_metric` immediately.** The baseline is the deliverable; a post with no baseline cannot be evaluated. Do not mark done until `record_metric` has executed and the value is logged.

## Quality bar
Would a knowledgeable reader learn something they couldn't get from a quick search? If not, rewrite or don't ship.

## Definition of done
- Brief locked; every stat has a source; company voice applied; one clear CTA present.
- Published, distribution queued, **baseline metric recorded and logged.**

## Common failure modes
- **Baseline not recorded.** The single most common gap — call `record_metric` before closing the task, not as a follow-up.
- **Fabricated stats.** One invented number destroys credibility for the whole piece.
- **Restating page-one results.** Adds no value; signals low quality to search and readers.
- **Skipping compliance check.** High risk on regulated topics; run it when in doubt.
