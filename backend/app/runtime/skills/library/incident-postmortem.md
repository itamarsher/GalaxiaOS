---
name: incident-postmortem
title: Incident Postmortem
description: Run a blameless postmortem that finds the systemic root cause and prevents recurrence.
roles: platform, governance, ceo
---
# Incident Postmortem

An incident you don't learn from will recur. This playbook runs a blameless postmortem that finds the
real systemic cause and produces concrete prevention — turning a failure into durable improvement.

## Workflow
1. **Build the timeline.** From `log_ops_event` and records, reconstruct what happened and when:
   detection, response, resolution. Facts first, before interpretation.
2. **Measure the impact.** Who/what was affected, for how long, and how badly (users, data, money,
   reputation). This calibrates how much prevention investment is warranted.
3. **Find the root cause, blamelessly.** Ask 'why' repeatedly past the surface trigger to the systemic
   cause — usually a missing safeguard, not a bad actor. Blame hides causes; the goal is a safer system, not
   a scapegoat.
4. **Assess the response.** What went well, what slowed resolution, what detection gap let it grow? The
   response is as important a lesson as the cause.
5. **Produce concrete prevention.** Specific, owned, dated actions that make recurrence impossible or
   detectable early — not vague "be more careful." `dispatch_tasks` with owners; `open_issue` for fixes.
6. **Document and share.** `create_report` (kind `incident_report`); `write_memory` (type `learning`) the
   systemic lesson; `update_company_playbook` if it changes a standing practice. Verify fixes actually land.

## Decision framework — systems, not people
A postmortem that ends at 'someone made a mistake' has failed. Humans err; robust systems make errors
harmless or visible. Always push to the systemic gap and fix that.

## Definition of done
- Factual timeline and impact established; root cause found blamelessly; response assessed.
- Concrete, owned, dated prevention actions created and tracked to completion; lesson documented.

## Common failure modes
- **Blame over cause.** Scapegoating stops the search before the real cause; guarantees recurrence.
- **Vague actions.** "Be more careful" prevents nothing.
- **No follow-through.** Prevention actions that are never verified as done.
