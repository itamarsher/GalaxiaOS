---
name: sprout-social
title: Sprout Social
description: Manage social engagement and publishing at scale — unify inboxes, run the content calendar with approvals, or pull cross-channel reports in Sprout Social.
roles: growth
---
# Sprout Social

Sprout Social unifies social management — the Smart Inbox, a shared publishing calendar, approval
workflows, listening, and strong reporting. This skill is the ABOS-adapted path to running it well:
**connect it as a tool first, never assume it's wired**, then remember every published post and reply
is gated external comms.

## Connect before you post
1. **Find the tool.** `discover_tools` with query `sprout`; it exposes as `mcp__sprout-social__*` once
   the founder has connected the social profiles. Load what you need with `use_tool`.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Sprout
   (MCP server or OAuth). Never invent a scheduled post, an inbox message, or a report figure — a
   phantom post is worse than none.
3. **Posts and replies are gated external comms.** Anything outbound is indexed and may need founder
   sign-off; use Sprout's message-approval workflow, don't route around it.

## Run it like a coordinated team
4. **Triage from the Smart Inbox.** Work mentions, comments, and DMs across all profiles in one stream;
   apply tags by topic and urgency so nothing slips and reporting can slice by theme later. Tag as you
   go — a clean tag library is what makes the analytics worth anything.
5. **Plan on the publishing calendar.** Draft ahead on the shared calendar to spot gaps and spacing;
   tag every post by campaign. The calendar plus approvals is what keeps a multi-profile team from
   collisions and off-brand posts.
6. **Enforce message approval.** Route brand/client drafts through the approval workflow so voice stays
   consistent and nothing publishes unreviewed — this is your ABOS sign-off gate in practice.
7. **Listen and report to decisions.** Run Listening topics with spike alerts to catch surges and
   trends early; build cross-channel reports (organic vs paid, competitor benchmarks) around one KPI
   per campaign. `read_metrics` and reconcile against the real dashboard before reporting a number.

## File the deliverable and record it
8. **File the plan and report.** `save_file` (category `artifact` or `brand`) the calendar and
   performance/listening report with the Sprout link — the durable, shareable record.
9. **Record + hand off.** `write_memory` (type `result`) what shipped and what performed;
   `record_metric` engagement/response time/conversions; `report_result` or `dispatch_task` next steps.

## Definition of done
- Sprout confirmed connected; brand posts routed through message approval, not around it.
- Inbox tagged and triaged, calendar planned, Listening topics and KPI reporting set.
- Real analytics filed, outcomes recorded, and follow-up handed off.

## Common failure modes
- **Phantom post.** Claiming content is scheduled when the account was never connected — escalate.
- **Untagged sprawl.** Skipping inbox/post tags, so reporting can't answer any real question.
- **Skipped approval.** Publishing straight to live profiles and bypassing the sign-off gate.
