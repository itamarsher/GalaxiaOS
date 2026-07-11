---
name: adobe-express
title: Adobe Express
description: Produce on-brand social, marketing, or design assets fast in Adobe Express — templates, quick edits, bulk variations, or a scheduled content run.
roles: design, growth
---
# Adobe Express

Adobe Express is the fleet's fast path to on-brand marketing and social assets — templates, quick photo
edits, bulk variations, scheduled posts. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then produce volume that stays on-brand.

## Connect before you create
1. **Find the tool.** `discover_tools` with query `adobe express`; it exposes as `mcp__adobe-express__*`
   once the founder has connected it. Load what you need with `use_tool` (create a project, export, schedule).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Adobe Express
   in Settings (MCP server or account). If the capability can't exist yet, `request_capability`.
   Never invent an asset link or claim a design exists — a phantom deliverable is worse than none.
3. **Least privilege + egress.** Assets and scheduled posts send content to a third party; if anything
   sensitive or unpublished is involved, `check_compliance` / `list_data_policies` first.

## Create on-brand and at volume
4. **Set up the Brand Kit first.** Load the company logo, colors, and fonts from `brand-identity-kit`
   into an Express Brand; use template locking so logo, colors, and key assets can't drift. Everything
   downstream inherits the brand instead of re-deciding it per asset.
5. **Start from a template, apply the brand.** Pick a template close to the format, then apply the Brand
   Kit — this is how a non-designer agent ships consistent output fast, not a blank-canvas gamble.
6. **Quick Actions for one-off edits.** Resize, remove background, convert, or crop with a single Quick
   Action rather than a full project — reserve full editing for real design work.
7. **Bulk Create for variations.** Drive up to ~99 variants from a spreadsheet of text/images (localized
   ads, per-segment creative) instead of hand-building each — the pro move for campaign volume.

## Schedule, file, and record it
8. **Scheduling/publishing is gated external comms.** Posting via Content Scheduler puts brand content in
   public channels — it's indexed into the external-comms log and may need founder sign-off. Respect the
   gate. If a run involves paid promotion, `request_budget` first (spend is metered).
9. **File and record.** `save_file` (category `brand` for assets, `artifact` for campaign exports) with
   links; `write_memory` (type `result`) what shipped; `record_metric` real post performance if tracked;
   `dispatch_task` follow-up, or `report_result`.

## Definition of done
- Adobe Express confirmed connected (or escalated, never faked); egress checked.
- Brand Kit applied (locked where it matters); made from templates/Quick Actions; bulk used for volume.
- Any scheduling passed the comms gate and budget check; assets filed, outcome recorded.

## Common failure modes
- **Phantom deliverable.** Claiming an asset exists when Express was never connected — escalate instead.
- **Off-brand drift.** Skipping the Brand Kit/locking, so colors, logo, and fonts wander per asset.
- **Silent publishing.** Scheduling posts around the external-comms gate instead of through sign-off.
