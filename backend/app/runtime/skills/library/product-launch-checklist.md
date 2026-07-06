---
name: product-launch-checklist
title: Product Launch Checklist
description: Run the pre-launch readiness gate so a feature ships without embarrassing gaps.
roles: product, platform, growth
---
# Product Launch Checklist

The moment before shipping is where preventable failures hide. This playbook is the readiness
gate that catches them — product, technical, GTM, and compliance — before users do.

## Workflow
1. **Confirm the feature meets its bar.** Acceptance criteria from the PRD met (`prd-writing`);
   beta exit criteria passed (`beta-program`); success metric instrumented (`record_metric` ready).
2. **Technical readiness.** With platform: tested, monitored, and a rollback path exists. Confirm
   scale/limits and that errors are observable. `dispatch_task` to verify, don't assume.
3. **Data & compliance gate.** `list_data_policies` and `check_compliance` for anything touching
   user data, payments, or regulated claims; `flag_legal_risk` on anything uncertain. This gate is
   not optional.
4. **GTM readiness.** Positioning/messaging ready, docs and release notes drafted
   (`release-notes`), support briefed, and the launch plan set (`product-launch-gtm`).
5. **Go/no-go.** Walk the checklist explicitly; a red item is a stop, not a footnote. For a
   material launch, `request_decision` for the CEO's go. `write_memory` (type `experiment`) the
   launch and its success metric.
6. **Post-launch watch.** Monitor the success metric and error signals for the first days;
   `report_result`; be ready to roll back (`incident-postmortem` if it goes wrong).

## Decision framework — ship or hold
Any unmet safety, data, or compliance item is a hold, full stop. Cosmetic gaps can ship with a
fast-follow; unsafe or non-compliant ones cannot.

## Definition of done
- Product, technical, data/compliance, and GTM items all green or explicitly waived with reason.
- Go/no-go recorded; success metric instrumented; post-launch watch in place.

## Common failure modes
- **Skipping the compliance/data gate** under deadline pressure — the most expensive shortcut.
- **No rollback path.** Shipping without an undo turns a bug into an incident.
- **Launching blind.** No instrumented metric means you can't tell if it worked.
