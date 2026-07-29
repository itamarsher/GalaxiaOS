---
name: landing-page-optimization
title: Landing Page Optimization
description: Use when a landing page's conversion rate is unclear, declining, or untested — to baseline, hypothesize, and run one isolated change.
roles: growth, product
---
# Landing Page Optimization

Improve conversion through one disciplined, hypothesis-led change at a time — not a redesign on a hunch.

**Leading word: BASELINE FIRST.** Every step is meaningless without a number to beat.

## Workflow
1. **BASELINE FIRST — capture it now.** `read_metrics` for current traffic and conversion rate.
   If no metric exists, `record_metric` to establish one before touching anything else.
2. **Diagnose the drop-off.** Walk the page as the visitor: value proposition clear in 5 seconds?
   One obvious action? Proof matches promise? Name the top 1–3 friction points.
3. **Form one hypothesis.** "Changing X will improve conversion because Y." One variable only —
   so the result is attributable. `write_memory` (type `experiment`).
4. **Make the change.** Rewrite copy (`draft_document`), swap a visual (`generate_image`), or
   `dispatch_task` to design/platform for structural edits. Keep it isolated.
5. **Measure honestly.** Wait for sufficient traffic before judging (see `ab-test-design` for sizing).
   `record_metric` after.
6. **Bank the learning.** `write_memory` (type `result`) win or lose; generalize winning patterns
   via `update_company_playbook`.

## Decision framework — what to test first
Order by impact × traffic: headline and primary CTA move the needle most. Don't polish button colors while the value proposition is unclear.

## Definition of done
- Baseline metric recorded before any change.
- One hypothesis, one isolated change, sufficient sample before verdict.
- Result written to memory; winning pattern added to playbook.

## Common failure modes
- **Skipping the baseline.** You cannot know if a change helped. BASELINE FIRST, always.
- **Changing multiple things at once.** You learn nothing about what worked.
- **Calling it early.** Small samples produce noise, not signal.
