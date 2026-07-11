---
name: mailchimp
title: Mailchimp
description: Send a campaign, build an automated journey, or manage the subscriber audience in Mailchimp when the fleet is emailing contacts and must protect deliverability.
roles: growth
---
# Mailchimp

Mailchimp is where the fleet runs email — broadcasts, automated journeys, and the subscriber audience
behind them. This skill is the ABOS-adapted path to using it well: **connect it as a tool first,
never assume it's wired**, and because every send is an external comm, **respect the approval gate
and protect the sender reputation.**

## Connect before you send
1. **Find the tool.** `discover_tools` with query `mailchimp`; it exposes as `mcp__mailchimp__*` once the
   founder has connected it. Load what you need with `use_tool` (create campaign, tag contacts, pull reports).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Mailchimp in
   Settings (API key). If it can't exist yet, `request_capability`. Never invent a send, open rate, or
   subscriber count — a phantom result is worse than none.
3. **Egress + gate.** Sending exports contact data to a third party and reaches real people — an external
   comm behind the approval gate. `check_compliance` / `list_data_policies` for consent before emailing.

## Structure so it lands and converts
4. **One audience, organized by tags and segments.** Don't split into multiple audiences. Tags are static
   labels; segments are live queries that rebuild on use. Tag by behavior/lifecycle, then segment to target.
5. **Map journeys to real behavior.** Build Customer Journeys with triggers, delays, and conditions —
   new subscriber, lead, buyer, inactive each get their own path. This beats one-size-fits-all blasts.
6. **Guard deliverability with list hygiene.** Only mail permissioned contacts; regularly clean bounces
   and unengaged addresses, and run a re-engagement path before purging. A dirty list tanks sender reputation.
7. **A/B before scaling.** Test subject line, content, and send time on a sample, then send the winner —
   don't guess on the full list.

## File the deliverable and record it
8. **Log the send, then file.** After it goes (through the gate), `save_file` (category `artifact`) the
   campaign summary/link, and pull real metrics with `use_tool` for the record.
9. **Record + hand off.** `write_memory` (type `result`/`learning`) what performed; `record_metric` for
   open/click/unsub; route replies or leads with `log_lead` / `crm_save_contact`; `report_result`.

## Definition of done
- Mailchimp connected (or escalated, never faked); consent checked; send cleared the gate.
- One audience with tags + segments; journeys mapped to behavior; list cleaned; A/B run before scale.
- Real metrics recorded, outcome filed and handed off.

## Common failure modes
- **Phantom send.** Claiming a campaign went out or citing open rates that don't exist — escalate instead.
- **Dirty list.** Mailing unpermissioned or stale contacts, so bounces wreck deliverability.
- **Audience sprawl.** Multiple audiences instead of tags/segments, so data fragments and billing balloons.
