---
name: kit
title: Kit (formerly ConvertKit)
description: Build creator email — newsletters, welcome sequences, tag-based automations, or commerce — when the audience lives (or should live) in Kit.
roles: growth
---
# Kit (formerly ConvertKit)

Kit (rebranded from ConvertKit) is the fleet's creator-email engine: broadcasts, visual automations,
tag-driven segmentation, and paid products, all on one subscriber profile. This skill is the
ABOS-adapted path to using it well: **connect it as a tool first, never assume it's wired**, then
build so tags — not lists — do the targeting.

## Connect before you send
1. **Find the tool.** `discover_tools` with query `kit`; it exposes as `mcp__kit__*` once it's connected (by you or the founder). Load what you need with `use_tool` (subscribers, sequences, broadcasts).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Kit in
   Settings (MCP server or API key). If the capability can't exist yet, `request_capability`. Never
   invent a broadcast, subscriber count, or automation — a phantom send is worse than none.
3. **Egress + comms gate.** Subscriber emails are personal data; `check_compliance` /
   `list_data_policies` before import/export. Every broadcast is outbound — it lands in the
   external-comms log and may need founder sign-off; respect the approval gate.

## Build so tags do the work
4. **Tag on behavior, don't build lists.** Kit has one central subscriber profile — model each signal
   (opened, clicked, purchased, joined-form-X) as a **tag**, then compose **segments** from tags. This
   gives precise micro-audiences without duplicate contacts and is what makes automations reusable.
5. **Visual automations as flowcharts.** Chain events → actions → conditions in the visual builder:
   entry (form/tag/purchase), then branch on behavior. Keep each automation single-purpose (welcome,
   nurture, win-back) so troubleshooting stays legible — not one mega-flow.
6. **Protect deliverability.** Authenticate the sending domain (SPF/DKIM/DMARC), keep the list clean by
   pruning cold subscribers, and send to engaged segments — sender reputation, not volume, decides
   inbox placement. Warm a new domain gradually.
7. **Commerce lives here too.** Digital products and paid newsletters run through Kit; a purchase fires
   a tag you can automate on. Any real charge or payout is metered — `request_budget` first.

## File the deliverable and record it
8. **File the artifact.** `save_file` the broadcast copy / automation map (category `artifact`, or
   `brand` for templated designs) with the Kit link in the description — the file store is durable,
   agent memory is not.
9. **Record + hand off.** After send, `record_metric` opens/clicks/conversions, `write_memory`
   (type `result`) the outcome, then `report_result` or `dispatch_task` for follow-up.

## Definition of done
- Kit confirmed connected (or escalated, never faked); subscriber-data egress and comms gate checked.
- Behavior modeled as tags/segments; automation single-purpose; sending domain authenticated.
- Broadcast/automation `save_file`d with link, metrics recorded, outcome handed off.

## Common failure modes
- **Phantom send.** Claiming a broadcast went out when Kit was never connected — escalate instead.
- **List thinking.** Duplicating subscribers across lists instead of one profile with tags, so
  segments rot and deliverability suffers.
- **Blasting cold contacts.** Sending to unengaged subscribers tanks sender reputation and inbox rate.
