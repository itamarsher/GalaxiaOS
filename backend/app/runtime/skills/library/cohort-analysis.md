---
name: cohort-analysis
title: Cohort Analysis
description: Group users by a shared start point to see how behavior and retention truly evolve over time.
roles: data, product, growth
---
# Cohort Analysis

Aggregate metrics hide the truth that new and old users behave differently. This playbook uses cohorts
to see how behavior actually evolves — revealing retention, decay, and improvement that averages mask.

## Workflow
1. **Pick the cohort dimension.** Usually signup period (weekly/monthly), but could be acquisition
   channel or plan. The dimension depends on the question you're answering. `write_memory` (type `experiment`).
2. **Define the behavior to track.** Retention, revenue, activation, or usage over time since the cohort's
   start. Use a precise definition (`kpi-definition`) so cohorts are comparable.
3. **Build the cohort table.** `read_metrics` to compute the metric per cohort across periods since start
   (period 0, 1, 2…). This is the shape averages can't show.
4. **Read the curves.** Does retention stabilize (a plateau = product-market fit signal) or decay to zero?
   Are newer cohorts better than older ones (a sign improvements are working)?
5. **Segment further where revealing.** Compare cohorts by channel or plan — you may find one source
   retains far better, which changes acquisition strategy (`unit-economics-analysis`, `paid-ads-campaign-launch`).
6. **Turn into action.** `write_memory` (type `learning`) the retention shape and the driver; route to
   `churn-reduction-playbook`, onboarding, or acquisition. `create_report` (kind `status_report`) if founder-relevant.

## Decision framework — the plateau is the signal
A retention curve that flattens above zero means a core of users find durable value — the foundation for
growth. A curve decaying to zero means fix retention before spending on acquisition, or you fill a leaky bucket.

## Definition of done
- Cohort dimension and behavior precisely defined; cohort-over-time table built from real data.
- Curves read for plateau/decay and cohort-over-cohort improvement; segmented; turned into an action.

## Common failure modes
- **Average blindness.** Aggregates hide that retention is collapsing beneath a growing top line.
- **Leaky-bucket spending.** Scaling acquisition before retention plateaus wastes budget.
- **Incomparable cohorts.** Inconsistent metric definitions make the table meaningless.
