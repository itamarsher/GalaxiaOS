---
name: company-okr-planning
title: Company OKR Planning
description: Set a small number of measurable objectives and key results that focus the whole fleet.
roles: ceo, governance
---
# Company OKR Planning

OKRs exist to focus a company on what matters and make progress measurable. This playbook sets a
tight, honest set that the fleet can actually rally behind — not a wishlist of everything.

## Workflow
1. **Start from the mission and constraints.** OKRs serve the mission under the real budget/runway
   (`runway-and-burn-analysis`, `get_company_playbook`). An objective the runway can't fund is a fantasy.
2. **Pick few objectives.** 2–3 qualitative, inspiring objectives for the period. More than that is
   no focus at all — the hardest part is deciding what NOT to do.
3. **Define measurable key results.** 2–4 per objective, each a number with a target and a baseline
   (`read_metrics`). "Improve onboarding" is not a KR; "raise activation from 30% to 50%" is.
4. **Make them a stretch, not a fantasy.** KRs should be hard but achievable. Sandbagging wastes the
   period; impossible targets get ignored. Aim for ~70% as a good outcome.
5. **Assign ownership.** Map each objective to the role(s) accountable; `set_agent_directive` so the
   fleet's work ladders to the OKRs. Cascade — team goals should support company goals.
6. **Publish and track.** `update_company_playbook` with the OKRs; `record_metric` the baselines;
   review progress on a cadence (`quarterly-strategy-review`). `write_memory` (type `experiment`).

## Decision framework — focus over coverage
When tempted to add an objective, cut one instead. A company that's focused on three things beats
one diffusely pursuing ten. OKRs are a filter, not a to-do list.

## Definition of done
- 2–3 objectives serving the mission within budget; 2–4 measurable KRs each with baseline+target.
- Stretch-but-achievable; owners assigned; published and instrumented for tracking.

## Common failure modes
- **Too many objectives.** No focus is worse than the wrong focus.
- **Unmeasurable KRs.** If you can't put a number on it, it's not a key result.
- **Set-and-ignore.** OKRs unreviewed mid-period drift into decoration.
