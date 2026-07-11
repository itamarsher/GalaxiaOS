---
name: zapier
title: Zapier
description: Wire two SaaS tools together with a trigger-action automation when a repetitive hand-off should run itself instead of an agent polling it.
roles: platform
---
# Zapier

Zapier connects the company's other SaaS tools with no-code trigger→action automations ("Zaps"). It is glue
between third parties, so every Zap is **data egress on a schedule** — it moves company data between vendors
without a human in the loop. The ABOS-adapted principle: **connect it as a tool first, never assume it's
wired**, then build Zaps that fail loudly, not silently.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `zapier`; it exposes as `mcp__zapier__*` once connected.
   Load what you need with `use_tool`.
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Zapier in
   Settings. Never claim a Zap is live when none exists — a phantom automation silently drops real work.
3. **Egress + spend.** Zaps consume metered tasks and push data to third parties; `check_compliance` if
   sensitive fields flow, and `request_budget` before standing up high-volume automations.

## Build Zaps that don't rot
4. **Filter early, right after the trigger.** Put the Filter immediately after the trigger and before any
   action — filters don't consume tasks, so a Zap that stops here wastes nothing and never creates half-built
   records downstream.
5. **Paths for branches, Filter for stop.** Use Filter when you only want the Zap to continue for matching
   data; use Paths when you must handle multiple outcomes (found vs. not found). Keep path conditions
   non-overlapping so one record never enrolls twice.
6. **Design for failure.** The mapping layer breaks silently when a source field is renamed or blank. Turn on
   Autoreplay for transient API errors, add an error Path or a Slack/email alert on failure, mind the 5 req/s
   and polling rate limits (add Delay steps), and audit task history on a schedule.

## File the deliverable and record it
7. **Document + record.** `write_memory` (type `result`) what the Zap does, its trigger, and where it can
   break; `save_file` a plain-language runbook so the next agent can debug it without opening Zapier blind.

## Definition of done
- Zapier confirmed connected (or escalated, never faked); egress/spend checked.
- Filter placed early; branches via non-overlapping Paths; Autoreplay + failure alert wired.
- Zap documented and outcome recorded.

## Common failure modes
- **Silent mapping break.** A renamed or empty source field produces incomplete records with no error — no
  guardrail catches it.
- **Rate-limit stall.** No Delay steps, so the connected app throttles Zapier and runs pile up held.
- **Overlapping Paths.** Loose conditions enroll the same record on two branches, double-processing it.
