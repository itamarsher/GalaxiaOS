---
name: hootsuite
title: Hootsuite
description: Schedule, monitor, or report on social across multiple networks from one place — bulk queues, listening streams, or team approval workflows in Hootsuite.
roles: growth
---
# Hootsuite

Hootsuite is the fleet's social command center — a column-based Streams view to monitor and engage,
plus scheduling, approvals, and cross-network analytics. This skill is the ABOS-adapted path to
running it well: **connect it as a tool first, never assume it's wired**, then remember every post
that leaves the queue is gated external comms.

## Connect before you post
1. **Find the tool.** `discover_tools` with query `hootsuite`; it exposes as `mcp__hootsuite__*` once
   the founder has connected the social accounts. Load what you need with `use_tool`.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Hootsuite
   (MCP server or OAuth). Never invent a scheduled post, a stream mention, or analytics numbers — a
   phantom post is worse than none.
3. **Posts are gated external comms.** Everything published is indexed into the external-comms log and
   may need founder sign-off. Route brand posts through Hootsuite's approval workflow, not around it.

## Run it like a command center
4. **Set up Streams to listen, not just broadcast.** Build columns for brand mentions, key hashtags,
   competitors, and intent phrases so you catch conversations in real time across networks side by side.
   Listening feeds the content, not the other way round.
5. **Bulk-schedule against a plan.** Use the bulk scheduler (CSV, up to hundreds of posts) to load a
   campaign calendar ahead, but tag every post by objective and campaign so reporting is automatic.
   Don't dump an unscheduled queue — space posts to each network's best windows.
6. **Enforce the approval workflow.** For any team or client account, route drafts through custom
   approval so nothing publishes accidentally and brand voice stays consistent. Track approval time and
   revisions to find bottlenecks. This is also your ABOS sign-off gate in practice.
7. **Report to decisions, not vanity.** Build reporting into the views that drive action — executive,
   channel, creator — with one primary KPI per campaign phase. `read_metrics` and reconcile against the
   real dashboard before you report a number.

## File the deliverable and record it
8. **File the plan and report.** `save_file` (category `artifact` or `brand`) the content calendar and
   performance report with the Hootsuite link — the durable, shareable record.
9. **Record + hand off.** `write_memory` (type `result`) what shipped and what performed;
   `record_metric` reach/engagement/conversions; `report_result` or `dispatch_task` the next batch.

## Definition of done
- Hootsuite confirmed connected; brand posts routed through approval, not around it.
- Listening Streams live, campaign bulk-scheduled and tagged, KPI-based reporting set.
- Real analytics filed, outcomes recorded, and follow-up handed off.

## Common failure modes
- **Phantom post.** Claiming content is scheduled when the account was never connected — escalate.
- **Broadcast-only.** Scheduling without Streams, so the fleet talks and never listens.
- **Skipped approval.** Publishing straight to live accounts and bypassing the sign-off gate.
