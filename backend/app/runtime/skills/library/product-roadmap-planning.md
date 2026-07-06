---
name: product-roadmap-planning
title: Product Roadmap Planning
description: Build a roadmap organized by outcomes and time horizons, honest about uncertainty.
roles: product, ceo
---
# Product Roadmap Planning

A roadmap aligns the fleet on where the product is headed. This playbook builds one around
outcomes and horizons — not a false-precision list of dated features.

## Workflow
1. **Anchor to objectives.** The roadmap serves company objectives/OKRs. Restate them; every
   roadmap theme must ladder up to one. Pull them from `get_company_playbook`.
2. **Organize by horizon, not hard dates:**
   - *Now* — committed, in progress, high confidence.
   - *Next* — validated problems queued (from `feature-prioritization`).
   - *Later* — directional bets, explicitly uncertain.
   Precision decreases with distance — say so.
3. **Frame as outcomes.** "Reduce time-to-value" beats "build onboarding wizard" — it states the
   goal and leaves room for the best solution.
4. **Cross-check capacity.** Confirm the Now column fits real capacity (`list_team`, effort
   estimates). An over-stuffed Now is a missed roadmap.
5. **Publish and version.** `create_report` (kind `status_report`) or `update_company_playbook`.
   The roadmap is a living artifact — date it and note what changed.
6. **Review on a cadence** (see `quarterly-strategy-review`); move items across horizons as
   evidence arrives; `write_memory` (type `learning`) why priorities shifted.

## Decision framework — commit vs. explore
Only the Now column is a commitment. Treat Next/Later as intent, not promises, so the roadmap
survives contact with reality and doesn't erode trust when it changes.

## Definition of done
- Themes ladder to objectives; organized by Now/Next/Later with honest uncertainty.
- Now fits real capacity; roadmap published, dated, and reviewed on a cadence.

## Common failure modes
- **Dated feature promises.** False precision that breaks trust when reality intervenes.
- **Output, not outcome.** Feature lists hide whether the goal is being served.
- **Set-and-forget.** A roadmap not revisited is fiction within a month.
