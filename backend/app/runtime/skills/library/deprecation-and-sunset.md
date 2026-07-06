---
name: deprecation-and-sunset
title: Deprecation & Sunset
description: Retire a feature or product responsibly, minimizing user harm and support fallout.
roles: product, platform
---
# Deprecation & Sunset

Removing something users rely on is as delicate as launching. This playbook retires a feature
with enough notice, migration help, and honesty to preserve trust.

## Workflow
1. **Justify the sunset.** Confirm the cost (maintenance, confusion, risk) outweighs the value to
   remaining users. `read_metrics` for real usage — you may find more dependence than expected.
   `request_decision` from the CEO for anything user-visible.
2. **Identify who's affected.** `crm_find_contacts` / usage data for users depending on it. The
   size and value of this group sets how careful the wind-down must be.
3. **Offer a path.** Provide a migration or alternative before removing the old thing. Sunsetting
   with no alternative is abandoning users — avoid it or explain honestly why none exists.
4. **Communicate early and clearly.** Announce the timeline well ahead (`send_email`,
   `publish_content`, `release-notes`). State what, when, why, and what to do. Repeat as the date nears.
5. **Wind down in stages.** Stop new adoption first, then remove for inactive users, then the rest —
   `dispatch_task` to platform. Keep a grace period and export path for user data (`list_data_policies`).
6. **Close out.** Confirm no critical dependence remains; `write_memory` (type `result`) the outcome
   and support impact; `log_ops_event`.

## Decision framework — remove vs. maintain
Sunset only when the ongoing cost clearly exceeds user value AND a reasonable path exists for
those affected. Speed of removal should scale inversely with how many depend on it.

## Definition of done
- Sunset justified by real usage/cost; affected users identified and given a path.
- Early, repeated, honest comms; staged wind-down with a data-export grace period.

## Common failure modes
- **Silent removal.** Breaking users without notice is the fastest trust-killer.
- **No migration path.** Leaving dependent users stranded.
- **Underestimating usage.** Check the data before assuming "no one uses this."
