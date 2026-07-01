---
name: crisis-and-incident-response
title: Crisis & Incident Response
description: Respond to a company-level crisis calmly and decisively, protecting users, trust, and the business.
roles: ceo, governance, platform
---
# Crisis & Incident Response

A crisis — outage, breach, PR event, key failure — is judged by the response as much as the event.
This playbook responds calmly and decisively: contain, communicate, resolve, learn.

## Workflow
1. **Assess severity fast.** What's the real impact — users harmed, data exposed, money at risk,
   reputation? Severity sets the response. Don't over-react to noise or under-react to a real breach.
2. **Contain first.** Stop the bleeding before explaining it — `pause_agent` a misbehaving agent,
   halt the harmful action, or `dispatch_task` platform to mitigate. Containment beats analysis while
   harm is ongoing.
3. **Escalate appropriately.** Anything involving user harm, data, legal exposure, or real money →
   `request_decision` / `request_user_action` to the founder immediately, and `flag_legal_risk` if
   relevant. Don't sit on a serious incident.
4. **Communicate honestly and promptly.** For anything affecting users, tell them what happened, what
   you're doing, and what they should do — via `send_notification` / `send_email`. Silence or spin turns
   an incident into a scandal. All external comms pass the governance gate.
5. **Resolve and verify.** Fix the root cause, not just the symptom; verify the fix holds before
   declaring resolution. `log_ops_event` throughout for the timeline.
6. **Learn.** Run a blameless `incident-postmortem`; `write_memory` (type `learning`) the systemic
   fix so the same crisis can't recur.

## Decision framework — contain, then communicate, then fix
Order matters under pressure: stop ongoing harm, tell affected people honestly, then fix root cause.
When severity is uncertain, escalate — over-escalating a false alarm costs far less than missing a real one.

## Definition of done
- Severity assessed; harm contained; serious incidents escalated to the founder immediately.
- Affected users told honestly and promptly; root cause fixed and verified; postmortem run.

## Common failure modes
- **Analysis before containment.** Explaining an incident while it's still causing harm.
- **Silence or spin.** Hiding an incident turns it into a trust catastrophe.
- **Symptom fixes.** Not addressing root cause invites the same crisis again.
