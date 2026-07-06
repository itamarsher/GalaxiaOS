---
name: product-analytics-review
title: Product Analytics Review
description: Read product usage data to find where users succeed, stall, and drop — and turn it into action.
roles: product, data
---
# Product Analytics Review

Usage data tells you what users actually do, not what they say. This playbook reads it to find
the highest-leverage improvement, not to admire dashboards.

## Workflow
1. **Start from a question.** "Where do new users drop before first value?" beats "let's look at
   the data." An analytics review with no question produces charts, not decisions.
2. **Pull the funnel.** `read_metrics` for the key flow (activation, core action, retention).
   Break it into steps and find the biggest drop-off — that's usually where the value is.
3. **Segment.** Overall averages hide truth; split by cohort, plan, or source (`cohort-analysis`).
   A metric flat overall may be soaring in one segment and sinking in another.
4. **Separate correlation from cause.** A behavior that correlates with retention isn't proven to
   cause it. Flag hypotheses for experiments (`ab-test-design`), don't assert causation.
5. **Turn findings into one action.** `write_memory` (type `learning`) the sharpest insight and
   the single change it implies; route it to `feature-prioritization` or `customer-onboarding-flow`.
6. **Report crisply.** `create_report` (kind `status_report`) with the question, the finding, and
   the recommended action — three things, not thirty charts.

## Decision framework — insight vs. metric
An insight changes a decision; a metric just describes. If a number wouldn't change what the
fleet does, don't spend the review on it.

## Definition of done
- Driven by a specific question; funnel broken down and segmented; biggest drop found.
- One recommended action produced and routed; causation claims labeled as hypotheses.

## Common failure modes
- **Dashboard tourism.** Looking at everything, deciding nothing.
- **Average blindness.** Segment or miss the real story.
- **Correlation as proof.** Confirm causal claims with an experiment.
