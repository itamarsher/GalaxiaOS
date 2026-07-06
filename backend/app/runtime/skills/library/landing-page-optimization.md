---
name: landing-page-optimization
title: Landing Page Optimization
description: Diagnose and improve a landing page's conversion with a clear hypothesis and one change at a time.
roles: growth, product, design
---
# Landing Page Optimization

This playbook improves a landing page's conversion rate through disciplined, hypothesis-led
changes — not a redesign on a hunch.

## Workflow
1. **Get the baseline.** `read_metrics` for current traffic and conversion. No baseline = no
   way to know if a change helped; establish it first.
2. **Diagnose the drop-off.** Walk the page as the visitor: is the value proposition clear in
   5 seconds? Is there one obvious action? Does the proof match the promise? List the top 1–3 friction points.
3. **Form one hypothesis.** "Changing X will improve conversion because Y." One variable at a
   time so the result is attributable. `write_memory` (type `experiment`).
4. **Make the change.** Rewrite copy (`draft_document`), swap a visual (`generate_image`), or
   `dispatch_task` to design/platform for structural edits. Keep the change isolated.
5. **Measure honestly.** Give it enough traffic to be meaningful before judging (see `ab-test-design`
   for sizing). `record_metric` before/after.
6. **Bank the learning.** `write_memory` (type `result`) whether the hypothesis held; feed
   winning patterns into the company playbook (`update_company_playbook`).

## Decision framework — what to test first
Order by impact × traffic: headline and primary CTA usually move the needle most. Don't A/B
button colors while the value proposition is unclear.

## Definition of done
- Baseline captured, one hypothesis, one isolated change, sufficient sample before a verdict.
- Result recorded; winning pattern generalized to the playbook.

## Common failure modes
- **Changing five things at once.** You learn nothing about what worked.
- **Calling it early.** Small samples produce noise, not signal.
- **Polishing details** while the core message is unclear.
