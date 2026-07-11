---
name: google-tag-manager
title: Google Tag Manager
description: Deploy, edit, or audit tracking tags, triggers, and the dataLayer through GTM — or wire consent-aware measurement without touching site code.
roles: growth, data
---
# Google Tag Manager

GTM is the control plane for a site's tracking — tags, triggers, variables, and the dataLayer — so
you deploy measurement without shipping code. This skill is the ABOS-adapted path to running it
cleanly: **connect it as a tool first, never assume it's wired**, then change containers the way a
governance tool demands — versioned, previewed, and consent-aware.

## Connect before you tag
1. **Find the tool.** `discover_tools` with query `tag manager`; GTM exposes as
   `mcp__google-tag-manager__*` once the founder has connected the account. Load with `use_tool`.
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect GTM (MCP
   server or account access). Never claim a tag is live or a container is published when it isn't — a
   phantom tag silently breaks measurement, which is worse than none.
3. **Tracking is data egress + consent.** Tags ship user data to third parties; `check_compliance` /
   `list_data_policies` before adding a tag that sends personal data, and gate it behind consent.

## Change the container like it's governed
4. **Build on a structured dataLayer.** Push clean, consistent events to `dataLayer` and read them via
   Data Layer Variables — don't scrape the DOM. For breaking changes, version the event
   (`add_to_cart_v2`) rather than mutating one live tags already consume.
5. **Consent Mode v2, non-negotiable.** Set `ad_user_data` and `ad_personalization` and use GTM's
   built-in consent APIs so state is consistent at trigger time. Ad/analytics tags must respect consent
   before they fire, or the deployment is a compliance liability.
6. **Preview, then version with notes.** Never publish blind — validate every change in Preview mode,
   confirm tags fire on the right triggers and no others, then publish a named version with a
   descriptive note. Version history is your rollback; treat the description as the audit trail.
7. **Fight tag sprawl on a cadence.** Audit regularly: pause or delete ghost tags from expired
   campaigns, consolidate near-duplicates with Lookup Tables/RegEx, and organize with folders. A
   cluttered container is how measurement quietly rots.

## File the deliverable and record it
8. **Document the container state.** `save_file` (category `artifact`) an export or change summary with
   the version name and what each tag measures — the durable record, not the agent's memory.
9. **Record + hand off.** `write_memory` (type `result` or `learning`) what was published and the
   rollback version; `record_metric` if it enables a new tracked event; `report_result` or
   `dispatch_task` the downstream analytics work.

## Definition of done
- GTM confirmed connected; consent/egress checked before any personal-data tag.
- Changes built on a structured dataLayer, Consent Mode v2 honored, previewed and versioned with notes.
- Container audited for sprawl; state filed, outcome recorded, and handed off.

## Common failure modes
- **Publish blind.** Skipping Preview and firing a broken or double-counting tag into production.
- **Consent afterthought.** Ad/analytics tags firing before consent — a live compliance breach.
- **Tag sprawl.** Ghost tags from dead campaigns piling up until no one trusts the numbers.
