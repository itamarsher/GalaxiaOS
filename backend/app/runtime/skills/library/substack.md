---
name: substack
title: Substack
description: Stand up or grow a publication on Substack — launch free vs paid tiers, work the recommendations/Notes network, or protect deliverability on sends.
roles: growth
---
# Substack

Substack is a newsletter-plus-network platform: free to start, a 10% cut on paid subscriptions, and a
built-in discovery flywheel through Recommendations and Notes. This skill is the ABOS-adapted path to
running it well: **connect it as a tool first, never assume it's wired**, then treat every send as
gated external comms with consent and deliverability duties.

## Connect before you publish
1. **Find the tool.** `discover_tools` with query `substack`; it exposes as `mcp__substack__*` once the
   founder has connected the account. Load what you need with `use_tool`.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Substack
   (MCP server or credentials). Never invent a subscriber count, an open rate, or a published post — a
   phantom post is worse than none.
3. **Sends are gated external comms.** A publish/email is indexed into the external-comms log and may
   need founder sign-off; subscribers must be real opt-ins. `check_compliance` before importing a list,
   and respect the approval gate.

## Set it up and work the network
4. **Decide free vs paid deliberately.** Publish free to build an audience first; turn on paid only
   when there's a clear reader payoff. A monthly price around $7-$10 with a discounted annual option is
   a sane start — avoid pricing so low it signals no value. Substack takes 10% of paid revenue.
5. **Work the Recommendations flywheel.** Recommend aligned publications and earn recommendations back —
   new subscribers are surfaced relevant pubs on signup, which compounds growth for free. This network,
   not paid ads, is the primary growth engine here.
6. **Grow with Notes, consistently.** Notes is the top on-platform growth surface: post a few times a
   week, engage with other writers daily, and reply to comments — the feed rewards activity and surfaces
   you to new readers. Feed it from your best post ideas rather than posting filler.
7. **Protect deliverability.** Keep a consistent cadence, write honest non-spammy subject lines, and let
   disengaged subscribers lapse rather than force-sending. `read_metrics` on your own opens before
   trusting generic benchmarks.

## File the deliverable and record it
8. **File the post and results.** `save_file` (category `artifact` or `brand`) the published post and a
   growth/performance summary with the Substack link — the durable, shareable record.
9. **Record + hand off.** `write_memory` (type `result`) subscriber growth and what converted to paid;
   `record_metric` opens/subs/paid-conversions from the real dashboard; `report_result` or `dispatch_task`.

## Definition of done
- Substack confirmed connected; sends cleared through consent and sign-off.
- Free/paid choice made intentionally; Recommendations and Notes worked as the growth engine.
- Real metrics filed, outcomes recorded, and follow-up handed off.

## Common failure modes
- **Phantom post.** Claiming a post published when the account was never connected — escalate instead.
- **Ignoring the network.** Skipping Recommendations and Notes, leaving the main growth lever unused.
- **Consent shortcut.** Importing a bought or scraped list and burning sender reputation on day one.
