---
name: blog-post-production
title: Blog Post Production
description: Use when you have a content brief (or enough inputs to reconstruct one) and need to produce, fact-check, publish, and instrument a single blog post.
roles: growth, research
---
# Blog Post Production

One job: take a content slot from brief to **published-and-measured**. Every step that doesn't serve that job is cut.

## Workflow

1. **Lock the brief.** Confirm target keyword, search intent, pillar, and the one action the reader should take. Pull missing inputs from `seo-keyword-strategy` or `content-marketing-calendar` before going further.

2. **Source before you write.** `web_search` for current facts, stats, and examples; log every URL. **Never invent a statistic, quote, or study result — cite it or cut it.** This is non-negotiable.

3. **Outline to the intent.** Answer-first for informational; comparison table for comparison; prominent CTA for transactional. Structure serves the query, not word count.

4. **Draft in company voice.** `draft_document` using voice guidelines from `get_company_playbook`. One original angle, concrete examples, no restatements of what's already on page one of search. Add a visual via `generate_image` only if it genuinely aids comprehension.

5. **Check before you ship.** Verify every claim against a logged source. Run `check_compliance` for regulated topics (health, finance, legal). Do not publish with an unsourced claim.

6. **Publish and instrument.** `publish_content` → `schedule_social_post` for distribution → **`record_metric` immediately to capture the baseline.** A post with no baseline cannot be evaluated; this step is required, not optional.

## Quality bar
Would a knowledgeable reader learn something they couldn't get from a quick search? If not, rewrite or don't ship.

## Definition of done
- Brief locked; every stat has a source; company voice applied; one clear CTA present.
- Published, distribution queued, **baseline metric recorded**.

## Common failure modes
- **No baseline recorded.** The single most common gap — instrumentation is part of the deliverable, not a follow-up.
- **Fabricated stats.** One invented number destroys credibility for the whole piece.
- **Restating page-one results.** Adds no value and signals low quality to search and readers alike.
- **Skipping compliance check.** High risk on regulated topics; run it when in doubt.
