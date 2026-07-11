---
name: webflow
title: Webflow
description: Build or update a CMS-backed marketing site in Webflow when the site lives (or should live) in a Webflow project and needs clean structure, SEO, and controlled publishing.
roles: growth, design
---
# Webflow

Webflow is where the fleet builds scalable, CMS-driven marketing sites that output semantic HTML.
This skill is the ABOS-adapted path to using it well: **connect it as a tool first, never assume
it's wired**, then lock the content model and class structure before designing so the site scales
and publishes deliberately.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `webflow`; Webflow exposes as `mcp__webflow__*` once it's connected (by you or the founder). Load what you need with `use_tool` (edit content, manage CMS items, publish).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Webflow in
   Settings (MCP or API key). If it can't exist yet, `request_capability`. Never invent a URL or claim a
   page is live — a phantom site is worse than none.
3. **Least privilege + egress.** Site content sent to Webflow leaves the company; if it carries anything
   sensitive, `check_compliance` / `list_data_policies` first.

## Build so it scales and ranks
4. **Lock the CMS model before design.** Separate collections — Posts, Authors, Categories, Tags — and
   link them with reference fields, not plain text, so filtering and internal linking work across hundreds
   of pages. Retrofitting the model later is expensive.
5. **Name classes semantically, reuse them.** Clean, reusable classes over one-off styles keep the DOM
   small and custom code easy to inject later. Avoid div-soup nesting.
6. **Set SEO at the collection level.** Dynamic title, meta description, and OG image bound to CMS fields
   so every generated page has real metadata, plus conditional visibility for optional fields. One H1,
   logical H2/H3.
7. **Understand staging vs production.** They're separate destinations, not versions. Publishing to
   staging leaves production on the old version. Before launch, confirm the page isn't blocked from
   indexing (Webflow doesn't disable staging indexing by default).

## File the deliverable and record it
8. **Publish through the gate, then file.** Publishing is an external comm — respect the approval gate,
   don't route around it. After it's live, `save_file` (category `artifact`) with the live URL, or use
   `publish_content` where that's the fleet's path.
9. **Record + hand off.** `write_memory` (type `result`) the URL and what shipped; `dispatch_task` growth
   to drive traffic, or `report_result`.

## Definition of done
- Webflow confirmed connected (or escalated, never faked); sensitive-data egress checked.
- CMS model locked with reference fields; semantic classes; collection-level SEO set.
- Published to production (not just staging) through the gate; URL filed, outcome recorded.

## Common failure modes
- **Phantom URL.** Claiming a page is live when Webflow was never connected — escalate instead.
- **Staging-only publish.** Pushing to staging and assuming production updated, so the site is stale.
- **Flat CMS model.** Overloading one collection instead of reference fields, so linking breaks at scale.
