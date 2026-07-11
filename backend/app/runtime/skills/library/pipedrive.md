---
name: pipedrive
title: Pipedrive
description: Design or run a sales pipeline, track deal activity, or report on conversion in Pipedrive when deals live (or should live) in Pipedrive CRM.
roles: growth
---
# Pipedrive

Pipedrive is the fleet's lightweight, activity-driven sales pipeline. This skill is the ABOS-adapted
path to using it well: **connect it as a tool first, never assume it's wired**, then design stages
and activities so no deal rots silently. ABOS mirrors the same deals internally
(`crm_save_deal`, `crm_list_deals`, `crm_log_activity`, `update_deal`) — keep them in sync.

## Connect before you touch deals
1. **Find the tool.** `discover_tools` with query `pipedrive`; it exposes as `mcp__pipedrive__*` once it's connected (by you or the founder). Load what you need with `use_tool` (create a deal, log an activity).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Pipedrive
   in Settings (API token or MCP server). Never invent a deal ID or claim a stage moved — a phantom
   pipeline is worse than none.
3. **Least privilege + egress.** Writing contact PII to Pipedrive is data egress; if sensitive data
   flows out, `check_compliance` / `list_data_policies` first.

## Design the pipeline to keep deals moving
4. **5-9 stages that match how you sell.** More is clutter, fewer hides signal. Use separate pipelines
   only for genuinely distinct sales processes (region/product), not per-rep. Each stage should reflect
   a real buyer commitment.
5. **Every deal has a next activity.** Pipedrive's core discipline: an open deal with no scheduled
   activity is a leak. Mirror scheduled follow-ups with `schedule_followup` so ABOS chases them too.
6. **Enable rotting per stage.** Set a rotting threshold matched to typical stage duration; rotting
   (pink) deals are your cue to follow up or close-lost. Automate stage-entry tasks with if-then
   workflows so nothing falls through.
7. **Audit monthly.** Review deal age, stage distribution, and rotting; archive 90+ day dead deals;
   build stage-to-stage conversion reports to find the leaking stage.

## File the deliverable and record it
8. **Export and file.** `save_file` the pipeline/conversion report (category `artifact`) with the
   Pipedrive link in the description.
9. **Record + hand off.** `write_memory` (type `result`) the pipeline state; `record_metric` for
   pipeline value and conversion; `report_result` or `dispatch_task` on stalled deals.

## Definition of done
- Pipedrive confirmed connected (or escalated, never faked); PII egress checked.
- 5-9 meaningful stages; every open deal has a next activity; rotting enabled and audited.
- Report filed with link; metrics recorded; ABOS CRM mirror kept in sync.

## Common failure modes
- **Phantom pipeline.** Reporting deals when Pipedrive was never connected — escalate instead.
- **Deals with no next activity.** Open deals nobody is chasing, quietly rotting to close-lost.
- **Stage sprawl.** Too many stages or per-rep pipelines, so conversion data is noise.
