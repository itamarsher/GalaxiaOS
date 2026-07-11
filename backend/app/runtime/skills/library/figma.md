---
name: figma
title: Figma
description: Produce or hand off UI designs, mockups, and design-system assets in Figma when the design lives (or should live) in a Figma file.
roles: design, product
---
# Figma

Figma is where the fleet's real UI design lives — mockups, prototypes, and the component library
that product and marketing build from. This skill is the ABOS-adapted path to using it well:
**connect it as a tool first, never assume it's wired**, then design so the file survives handoff.

## Connect before you design
1. **Find the tool.** `discover_tools` with query `figma`; Figma exposes as `mcp__figma__*` once it's connected (by you or the founder). Load what you need with `use_tool` (e.g. read a file, export a frame).
2. **Not connected? Connect it yourself — don't fake it.** You can onboard this yourself — sign up for the service and self-issue an API key/token, then wire it up with `connect_service` (a name, the service's MCP endpoint, and the token) so its tools come online for you on the next step, no founder needed. Only if you genuinely can't get credentials — it needs the founder's identity, payment, or a login only they have — `request_user_action` for the founder to connect Figma in
   Settings (MCP server or personal-access token). If the capability genuinely can't exist yet,
   `request_capability`. Never invent a Figma link or claim a frame exists — a phantom design is worse
   than none.
3. **Least privilege + egress.** Reading/writing Figma sends company design data to a third party; if a
   file carries anything sensitive, `check_compliance` / `list_data_policies` first.

## Design so it survives handoff
4. **Components + variants, not copies.** Build reusable components; use **variants** for states of the
   *same* object (default/hover/disabled), separate components for genuinely different objects. A variant
   set should read like an obvious grid, not a junk drawer — this is what maps cleanly to code.
5. **Auto Layout on anything that responds to content.** Buttons, cards, lists, sections. Auto Layout
   mirrors Flexbox/Grid, so the handoff produces predictable CSS instead of pixel-pushing.
6. **Derive tokens from the brand.** Colors, type scale, spacing come from `brand-identity-kit` /
   `design-system-setup` — Figma is where the brand becomes buildable, not a separate aesthetic.
7. **Name and mark for the developer.** Clear page/frame names, annotations for specs, and "Ready for
   Dev" on frames that are done. A developer (or the platform agent) must be able to navigate the file
   without you in the room.

## File the deliverable and record it
8. **Export and file.** Export the final frames/assets and `save_file` (category `artifact`, or `brand`
   for design-system assets) with the Figma link in the description — the file store is the durable,
   shareable source, not the agent's memory.
9. **Record + hand off.** `write_memory` (type `result`) the file link and what shipped; `dispatch_task`
   the platform agent to implement in code, or `report_result`.

## Definition of done
- Figma confirmed connected (or escalated, never faked); sensitive-data egress checked.
- Components/variants/Auto Layout used; tokens from the brand; frames named and marked Ready for Dev.
- Final assets exported, `save_file`d with the link, outcome recorded and handed off.

## Common failure modes
- **Phantom design.** Claiming a mockup exists when Figma was never connected — escalate instead.
- **Detached copies over components.** Duplicated frames that can't be updated once, so the system rots.
- **Handoff with no structure.** Unnamed frames and no annotations force a re-design at implementation.
