---
name: framer
title: Framer
description: Build, update, or publish a marketing site or landing page in Framer when the site lives (or should live) in a Framer project rather than hand-coded.
roles: design, growth
---
# Framer

Framer is where the fleet ships fast, no-code marketing sites and landing pages that come out as
performant, SEO-clean HTML. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then build so the site is responsive,
CMS-driven, and actually indexable before you hit publish.

## Connect before you build
1. **Find the tool.** `discover_tools` with query `framer`; Framer exposes as `mcp__framer__*` once the
   founder has connected it. Load what you need with `use_tool` (edit a page, add CMS items, publish).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Framer in
   Settings (MCP or API key). If it can't exist yet, `request_capability`. Never invent a published URL
   or claim a page is live — a phantom site is worse than none.
3. **Least privilege + egress.** Site content sent to Framer leaves the company; if it carries anything
   sensitive, `check_compliance` / `list_data_policies` first.

## Build so it publishes clean
4. **Design desktop-first, then fix each breakpoint.** Framer cascades from the 1200px desktop down;
   check the tablet and 390px mobile breakpoints and override where the layout breaks — don't ship only
   the desktop view.
5. **Model repeatable content as CMS collections.** Blog posts, case studies, changelog — a collection
   with fields plus one template page, not hand-built pages. This is what scales to hundreds of pages.
6. **Reuse components, derive style from the brand.** Build components for headers, cards, CTAs; pull
   colors and type from the `brand-identity-kit` so the site matches the rest of the fleet's output.
7. **Set SEO before publish.** Unique title + meta description per page, one H1 then logical H2/H3, OG
   image, and dynamic SEO fields on CMS template pages so generated pages don't inherit weak metadata.

## File the deliverable and record it
8. **Publish through the gate, then file.** Publishing is an external comm — respect the approval gate,
   don't route around it. After it's live, `save_file` (category `artifact`) with the live URL, or use
   `publish_content` where that's the fleet's path.
9. **Record + hand off.** `write_memory` (type `result`) the URL and what shipped; `dispatch_task` growth
   to drive traffic, or `report_result`.

## Definition of done
- Framer confirmed connected (or escalated, never faked); sensitive-data egress checked.
- All breakpoints checked; repeatable content in CMS; per-page SEO set before publishing.
- Site published through the gate, URL filed, outcome recorded and handed off.

## Common failure modes
- **Phantom URL.** Claiming a page is live when Framer was never connected — escalate instead.
- **Desktop-only ship.** Skipping mobile breakpoints, so the live site is broken on phones.
- **Publish then optimize.** Shipping with default metadata and no H1 structure, so nothing ranks.
