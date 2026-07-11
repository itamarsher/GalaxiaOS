---
name: beehiiv
title: beehiiv
description: Grow, send, or monetize a newsletter on beehiiv — segment sends, wire the referral/Boosts program, or set up ad-network revenue and deliverability.
roles: growth
---
# beehiiv

beehiiv is a newsletter platform built for growth and monetization — segmentation, a referral
program, Boosts, an ad network, and native deliverability tooling. This skill is the ABOS-adapted
path to running it well: **connect it as a tool first, never assume it's wired**, then treat every
send as gated external comms with consent and deliverability duties.

## Connect before you send
1. **Find the tool.** `discover_tools` with query `beehiiv`; it exposes as `mcp__beehiiv__*` once the account is connected (by you or the founder). Load what you need with `use_tool`.
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect beehiiv
   (MCP server or API key). Never invent a subscriber count, an open rate, or a sent issue — a phantom
   send is worse than none.
3. **Sends are gated external comms.** A broadcast is indexed into the external-comms log and may need
   founder sign-off; subscribers must be genuine opt-ins. `check_compliance` before importing a list,
   and respect the approval gate rather than blasting.

## Grow and monetize the list
4. **Authenticate the domain first.** Set up domain authentication (SPF/DKIM) before any real send —
   the highest-leverage five minutes for deliverability. Keep sending patterns consistent and prune
   disengaged subscribers so the list stays inbox-worthy.
5. **Segment instead of blasting everyone.** Use behavioral triggers (link clicks, referral activity,
   survey answers) to target segments; personalized sends materially lift conversion. Short subject
   lines and a consistent early send window open best — but `read_metrics` on your own audience rather
   than trusting generic benchmarks.
6. **Turn on referrals and Boosts.** The built-in referral program compounds subscriber growth; enable
   Boosts to acquire subscribers from other newsletters. Boosts spend real money — `request_budget`
   before enabling paid acquisition.
7. **Layer monetization deliberately.** Paid subscriptions and the ad network are the main revenue
   channels; ad placements are outbound and must stay on-brand, so route sponsor content through
   sign-off. A weekly cadence with a clear reader payoff is what converts free readers to paid.

## File the deliverable and record it
8. **File the issue and results.** `save_file` (category `artifact` or `brand`) the sent issue and a
   performance summary with the beehiiv link — the durable record, not the agent's memory.
9. **Record + hand off.** `write_memory` (type `result`) subscriber growth and what converted;
   `record_metric` opens/clicks/subs/revenue from the real dashboard; `report_result` or `dispatch_task`.

## Definition of done
- beehiiv confirmed connected; domain authenticated; sends cleared through consent and sign-off.
- Segmented, deliverability-sound send out; referral/Boosts and monetization configured intentionally.
- Real metrics filed, outcomes recorded, and follow-up handed off.

## Common failure modes
- **Phantom send.** Claiming an issue went out when the account was never connected — escalate instead.
- **Unauthenticated blast.** Sending before domain auth, landing the whole list in spam.
- **Consent shortcut.** Importing a bought or scraped list and burning sender reputation on day one.
