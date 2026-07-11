---
name: canva
title: Canva
description: Produce on-brand marketing graphics, social posts, decks, or ad creative fast when the asset should be built and resized in Canva rather than hand-designed.
roles: design, growth
---
# Canva

Canva is where the fleet turns brand into volume — social posts, decks, ad variants, one-pagers,
all reusing one visual system. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then design inside the Brand Kit so
everything the fleet ships stays on-brand without a designer in the loop.

## Connect before you design
1. **Find the tool.** `discover_tools` with query `canva`; Canva exposes as `mcp__canva__*` once the
   founder has connected it. Load what you need with `use_tool` (create a design, apply a template, export).
2. **Not connected? Ask — don't fake it.** `request_user_action` for the founder to connect Canva in
   Settings (MCP or API key). If the capability can't exist yet, `request_capability`. Never invent a
   Canva link or claim an asset exists — a phantom design is worse than none.
3. **Least privilege + egress.** Designs sent to Canva carry company brand data to a third party; if a
   design includes anything sensitive, `check_compliance` / `list_data_policies` first.

## Design so it stays on-brand at volume
4. **Set the Brand Kit as the source of truth.** Pull logos, colors, fonts, and icons from the
   `brand-identity-kit`; a Brand Kit holds them so every design applies the brand in one click, not by eye.
5. **Build from Brand Templates, not blank canvases.** Lock layout and lock brand elements; leave only
   swappable slots. Use SVG icons so they recolor cleanly. This is what lets non-designer agents produce
   consistent output.
6. **Batch with Resize / Magic Switch.** Design once, then reformat to every channel's dimensions
   (post, story, ad, banner) in one action — don't rebuild per platform.
7. **Use Magic Studio as first draft, not final.** AI generation and background removal speed drafts, but
   review for brand accuracy and hallucinated text before anything ships.

## File the deliverable and record it
8. **Export and file.** Export final assets (PNG/PDF/MP4) and `save_file` (category `brand` for
   reusable brand assets, `artifact` for campaign one-offs) with the Canva link in the description.
9. **Record + hand off.** `write_memory` (type `result`) the links and what shipped; `dispatch_task` the
   growth agent to schedule or publish, or `report_result`. Publishing/ads stay gated — don't route around it.

## Definition of done
- Canva confirmed connected (or escalated, never faked); sensitive-data egress checked.
- Assets built from Brand Kit + Brand Template; resized per channel; Magic Studio output reviewed.
- Final assets exported, `save_file`d with the link, outcome recorded and handed off.

## Common failure modes
- **Phantom asset.** Claiming a graphic exists when Canva was never connected — escalate instead.
- **Off-brand freelancing.** Designing outside the Brand Kit, so colors and fonts drift per asset.
- **One-off per platform.** Rebuilding by hand instead of Resize, wasting time and inviting inconsistency.
