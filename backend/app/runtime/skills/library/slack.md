---
name: slack
title: Slack
description: Set up channels, post updates, or wire workflows in a real Slack workspace when the fleet needs to reach human teammates where they already work.
roles: ceo, platform
---
# Slack

Slack is where the company's humans actually talk — so it is an **outbound, indexed comms surface**, not the
fleet's internal bus. Use `message_teammate` / `send_chat_message` between agents; reach into Slack only to
touch real people. The ABOS-adapted principle: **connect it as a tool first, never assume it's wired**, then
post like a disciplined operator, not a firehose.

## Connect before you post
1. **Find the tool.** `discover_tools` with query `slack`; it exposes as `mcp__slack__*` once it's connected (by you or the founder). Load what you need with `use_tool` (send a message, create a channel, search).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Slack in Settings
   (MCP server or bot token). Never invent a channel link or claim a message was posted — a phantom post is
   worse than none.
3. **Outbound is gated.** Messages to humans land in the external-comms log and may need founder sign-off;
   respect the approval gate and `check_compliance` if anything sensitive leaves the fleet.

## Post like an operator
4. **Name channels on a convention.** Prefix by purpose — `team-`, `proj-`, `ops-`, `announce-`, `ext-` for
   Slack Connect. Consistent prefixes sort alphabetically and stop sprawl; archive dead channels after a
   30-60 day aftercare window rather than deleting them.
5. **Thread everything; broadcast almost never.** Replies go in threads to keep the channel scannable. Reserve
   `@here`/`@channel` for genuinely urgent, actionable, real, unique alerts — noise trains people to mute you.
6. **Automate the routine with Workflow Builder.** Standing asks — intake, approvals, standups — belong in a
   workflow, not a human re-typing. Keep alerts actionable and de-duplicated so the channel stays signal.

## File the deliverable and record it
7. **Record the touchpoint.** `write_memory` (type `result`) the channel/permalink and what was communicated;
   `record_metric` if it drove a measurable outcome. `save_file` any exported thread or canvas worth keeping.

## Definition of done
- Slack confirmed connected (or escalated, never faked); outbound approval gate respected.
- Channel named on-convention, message threaded, broadcasts used sparingly.
- Touchpoint recorded and any durable artifact filed.

## Common failure modes
- **Phantom post.** Claiming a message was sent when Slack was never connected — escalate instead.
- **Broadcast spam.** `@channel` for non-urgent notes; the team mutes you and misses the real alert.
- **Channel sprawl.** Ad-hoc names with no prefix or archiving, so nobody can find the right room.
