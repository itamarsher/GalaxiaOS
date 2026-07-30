---
name: landing-page-optimization
title: Landing Page Optimization
description: Use when editing landing page copy, layout, or CTAs, or when conversion rate is unknown, unclear, or declining — fires before any change begins.
roles: growth, product
---
# Landing Page Optimization

Improve conversion through one disciplined, hypothesis-led change at a time — not a redesign on a hunch.

**Leading word: INSTRUMENTED.** Every engagement ends with a tracked KPI. If no metric exists when you arrive, creating one is Step 1 — mandatory, not optional, not deferred.

## Workflow
1. **INSTRUMENTED — record the baseline now.** `read_metrics` for current traffic and conversion rate. If no metric exists, `record_metric` immediately and confirm it persists beyond the test window. Do not proceed until a number exists.
2. **Diagnose friction.** Walk the page as the visitor: value proposition clear in 5 seconds? One obvious CTA? Proof matches promise? Name the top 1–3 friction points.
3. **Form one hypothesis.** "Changing X will improve conversion because Y." One variable only — so the result is attributable. `write_memory` (type `experiment`).
4. **Make the isolated change.** Rewrite copy (`draft_document`), swap a visual (`generate_image`), or `dispatch_task` for structural edits. Touch nothing else.
5. **Measure honestly.** Wait for sufficient traffic (see `ab-test-design` for sizing). `record_metric` after the test window.
6. **Bank the learning.** `write_memory` (type `result`); add winning patterns via `update_company_playbook`. Confirm the KPI is still active — INSTRUMENTED means it outlives this engagement.

## Decision framework — what to test first
Order by impact × traffic: headline and primary CTA move the needle most. Don't polish button colors while the value proposition is unclear.

## Definition of done
- Baseline metric recorded **and confirmed to track ongoing** before any change.
- One hypothesis, one isolated change, sufficient sample before verdict.
- Result in memory; winning pattern in playbook; KPI active after engagement closes.

## Common failure modes
- **No ongoing instrumentation.** The metric must survive the test window — this is the most common gap and the most costly. INSTRUMENTED means it persists.
- **Skipping the baseline.** A number must exist before you touch anything.
- **Changing multiple things at once.** You learn nothing about what worked.
- **Calling it early.** Small samples produce noise, not signal.
