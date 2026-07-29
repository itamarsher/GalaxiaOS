---
name: landing-page-optimization
title: Landing Page Optimization
description: Use when asked to improve, diagnose, or test a landing page — fires at first sign of a conversion problem, unclear baseline, or proposed page change.
roles: growth, product
---
# Landing Page Optimization

Improve conversion through one disciplined, hypothesis-led change at a time — not a redesign on a hunch.

**Leading word: BASELINE FIRST.** No change is meaningful without a number to beat. If no metric exists, creating one is the first deliverable.

## Workflow
1. **BASELINE FIRST — capture it now.** `read_metrics` for current traffic and conversion rate.
   If no metric exists, `record_metric` immediately — this is the output of Step 1, not a pre-condition.
2. **Diagnose friction.** Walk the page as the visitor: value proposition clear in 5 seconds? One obvious action? Proof matches promise? Name the top 1–3 friction points.
3. **Form one hypothesis.** "Changing X will improve conversion because Y." One variable only — so the result is attributable. `write_memory` (type `experiment`).
4. **Make the isolated change.** Rewrite copy (`draft_document`), swap a visual (`generate_image`), or `dispatch_task` for structural edits. Touch nothing else.
5. **Measure honestly.** Wait for sufficient traffic (see `ab-test-design` for sizing). `record_metric` after.
6. **Bank the learning.** `write_memory` (type `result`); add winning patterns via `update_company_playbook`.

## Decision framework — what to test first
Order by impact × traffic: headline and primary CTA move the needle most. Don't polish button colors while the value proposition is unclear.

## Definition of done
- Baseline metric recorded before any change (even if you had to create it).
- One hypothesis, one isolated change, sufficient sample before verdict.
- Result written to memory; winning pattern added to playbook.

## Common failure modes
- **Skipping the baseline.** BASELINE FIRST — if no metric exists, record one before touching the page.
- **Changing multiple things at once.** You learn nothing about what worked.
- **Calling it early.** Small samples produce noise, not signal.
- **No instrumentation after the engagement.** The KPI must be tracked ongoing, not just for the test window.
