---
name: weekly-company-standup
title: Weekly Company Standup
description: Synthesize the fleet's week into a shared picture of progress, blockers, and the week's focus.
roles: ceo
---
# Weekly Company Standup

The fleet works in parallel; without synthesis it loses shared context. This playbook produces a
weekly picture of what moved, what's stuck, and what matters next — coordination, not status theater.

## Workflow
1. **Pull the real state.** `list_team` and recent activity, `read_metrics` for the numbers, and
   blockers surfaced across roles (`read_chat_channel`, decision inbox). Ground it in evidence, not vibes.
2. **Report progress against OKRs.** For each active objective (`company-okr-planning`), what moved
   this week and by how much? Tie work to goals so progress is visible, not just busyness.
3. **Surface blockers explicitly.** What's stuck and who owns unblocking it? A standup's main value is
   making blockers visible so they get cleared — `dispatch_task` / `request_decision` on the real ones.
4. **Set the week's focus.** The 1–3 things that matter most this week. Broadcast so the fleet aligns
   (`set_agent_directive`, `send_chat_message`). Focus beats a long undifferentiated list.
5. **Flag risks early.** Runway, at-risk deals, slipping objectives — name them while they're cheap to
   fix (`runway-and-burn-analysis`, `deal-pipeline-review`).
6. **Publish.** `create_report` (kind `status_report`) or post to the company channel; `write_memory`
   (type `learning`) recurring blockers worth a systemic fix.

## Decision framework — coordination over recitation
Spend the standup on blockers and the week's focus, not on everyone reciting activity. If an item
wouldn't change what anyone does, it belongs in a log, not the standup.

## Definition of done
- State pulled from real activity and metrics; progress tied to OKRs; blockers surfaced with owners.
- Week's 1–3 focus set and broadcast; risks flagged early; published.

## Common failure modes
- **Status theater.** Activity recitation that coordinates nothing.
- **Invisible blockers.** The one thing a standup must surface, left unsaid.
- **No focus.** A flat list with no priorities leaves the fleet to guess.
