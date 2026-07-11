---
name: buffer
title: Buffer
description: Schedule, queue, or analyze social posts across channels in Buffer when the company's social publishing runs (or should run) through Buffer.
roles: growth
---
# Buffer

Buffer is where the fleet queues and schedules social content across channels — with per-channel timing,
analytics, and an approval workflow. This skill is the ABOS-adapted path to using it well: **connect it as
a tool first, never assume it's wired**, then schedule for consistency and route every post through the gate.

## Connect before you schedule
1. **Find the tool.** `discover_tools` with query `buffer`; it exposes as `mcp__buffer__*` once the founder
   has connected the channels. Load what you need with `use_tool` (queue a post, read analytics, list channels).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Buffer and the
   specific channels in Settings (MCP server or access token). Never claim a post published or invent
   engagement numbers — a phantom post erodes trust with the audience and the founder.
3. **Egress + brand.** Posts carry brand voice and company data outward; pull tone and assets from the
   brand kit, and `check_compliance` if a post references anything sensitive.

## Schedule for consistency, tune per channel
4. **Set a cadence, then a schedule.** Consistency beats bursts: ~2–5 posts/week per channel is a sound
   baseline (X tolerates several/day; LinkedIn posts have a long shelf life, so fewer, richer posts win).
   Use Buffer's per-channel recommended times / posting goals rather than one global slot.
5. **One queue per channel, tailored.** Don't cross-post identical copy — reshape length, hashtags, and
   first comment per network. Buffer's channel queues exist so each platform gets native-feeling content.
6. **Read analytics, act on it.** Pull Buffer analytics for real reach/engagement per post and time; shift
   the schedule toward what actually performs. Report only Buffer's real numbers — never estimate reach.
7. **Route through approval — always gated.** Published social is external comms indexed into the comms log
   and typically needs founder sign-off. Use Buffer's draft/approval workflow and ABOS gating together;
   never publish immediately around the gate. `schedule_social_post`/`publish_content` respect the same rule.

## File the deliverable and record it
8. **File the calendar.** `save_file` (category `brand`) the content calendar/queue plan with the Buffer link
   in the description — the durable, shareable source of what's scheduled.
9. **Record + report.** After posts run, `record_metric` real engagement, `write_memory` (type `result` or
   `learning`) what performed, and `report_result`.

## Definition of done
- Buffer + channels confirmed connected (or escalated, never faked); brand voice and sensitive content checked.
- Cadence set with per-channel recommended times, copy tailored per queue, schedule tuned from real analytics.
- Every post passed the approval gate; calendar filed with the link, real engagement recorded.

## Common failure modes
- **Phantom post.** Claiming content published when Buffer was never connected — escalate instead.
- **Identical cross-post.** Same copy everywhere, ignoring each channel's native format.
- **Routing around the gate.** Publishing immediately to skip approval — respect the external-comms gate.
