---
name: logo-and-visual-assets
title: Logo & Visual Assets
description: Produce a logo and core visual assets that are distinctive, versatile, and on-brand.
roles: design, growth
---
# Logo & Visual Assets

The logo and core marks are the most-repeated expression of the brand. This playbook produces them
to be distinctive, legible everywhere, and consistent with the identity.

## Workflow
1. **Brief from the brand kit.** Pull direction, palette, and personality from `brand-identity-kit`.
   A logo produced without the brand kit will clash with everything else.
2. **Explore options.** `generate_image` several distinct directions rather than polishing the first
   idea. Distinctiveness matters — the mark must not look like every competitor.
3. **Test versatility.** A good logo works small (favicon), in one color, on light and dark, and at a
   glance. Reject beautiful marks that fail these real constraints.
4. **Produce the asset set.** Primary logo, simplified/mark-only version, light/dark variants, and an
   icon. Downstream assets need all of these, not just the hero version.
5. **Check for conflicts.** `web_search` to ensure the mark isn't confusingly similar to an existing
   brand; `flag_legal_risk` if there's a possible trademark clash — a logo that infringes is a liability.
6. **Deliver and document.** `save_file` the asset set with usage notes; `update_company_playbook`.
   `write_memory` (type `result`) the final direction so it's not relitigated.

## Decision framework — versatility over beauty
Choose the mark that works across every real context (tiny, one-color, dark mode) over the prettiest
one that only shines in the hero shot. A logo lives at 16px more than in a showcase.

## Definition of done
- Briefed from the brand kit; multiple directions explored; versatility tested against real constraints.
- Full variant set produced; trademark-conflict checked; delivered and documented in the playbook.

## Common failure modes
- **First-idea polish.** Refining one concept instead of exploring distinct options.
- **Hero-only design.** Marks that break at small size or in one color.
- **Trademark blindness.** Shipping a mark that clashes with an existing brand.
