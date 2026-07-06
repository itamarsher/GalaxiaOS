---
name: customer-segmentation
title: Customer Segmentation
description: Group the market into actionable segments by need and behavior so GTM can target sharply.
roles: research, growth, product
---
# Customer Segmentation

Treating all customers the same wastes effort on the wrong ones. This playbook builds segments
that are actually actionable — distinct in need, reachable, and worth serving.

## Workflow
1. **Segment on need and behavior, not just demographics.** Firmographics (size, industry) are a
   starting point, but the useful cut is by problem intensity, use case, and buying behavior — pull
   from `product-discovery-interviews` and `crm_contact_timeline`.
2. **Ensure segments are actionable.** Each segment must be (a) distinct in what it needs, (b)
   reachable through some channel, and (c) large/valuable enough to serve. Segments failing these
   are academic.
3. **Profile each segment:** its core job (`jobs-to-be-done-analysis`), willingness to pay, where it
   congregates, and how it buys. `write_memory` (type `learning`) per segment.
4. **Rank by fit and value.** Score segments on problem-fit × reachability × value. Identify the 1–2
   beachhead segments to focus GTM on now.
5. **Validate with data.** Cross-check against real customers (`read_metrics`, `cohort-analysis`) —
   which segment actually activates, retains, and pays? Reality beats the whiteboard.
6. **Drive downstream.** Feed the beachhead into `positioning-and-messaging`, targeting
   (`paid-ads-campaign-launch`), and roadmap (`feature-prioritization`).

## Decision framework — focus over coverage
Pick a beachhead and win it before widening. A sharp segment you dominate beats broad, shallow
presence across many. Segmentation exists to enable focus, not to catalog everyone.

## Definition of done
- Segments cut by need/behavior, each distinct, reachable, and valuable.
- Profiled and ranked; beachhead chosen and validated against real customer data.

## Common failure modes
- **Demographics-only.** "Companies with 50–200 employees" isn't a need; it's a filter.
- **Un-actionable segments.** Distinct but unreachable = useless.
- **No focus.** Segmentation that leads to targeting everyone defeats its purpose.
