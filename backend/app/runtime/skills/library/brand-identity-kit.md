---
name: brand-identity-kit
title: Brand Identity Kit
description: Define a coherent brand identity — voice, look, and values — that every asset can draw from.
roles: design, growth, ceo
---
# Brand Identity Kit

A brand is the consistent impression a company makes. This playbook defines the identity once so
every downstream asset — site, deck, social, product — is coherent instead of improvised.

## Workflow
1. **Root it in positioning.** The brand expresses the positioning and mission (`positioning-and-messaging`,
   `get_company_playbook`). Identity divorced from strategy is decoration; grounded, it reinforces the message.
2. **Define the verbal identity.** Voice and tone (e.g. plain and confident vs. playful), key phrases,
   and words to avoid. This governs all copy — `draft_document` a short voice guide with examples.
3. **Define the visual identity.** Logo direction, color palette (with meanings), typography, and imagery
   style. Keep it simple and distinctive; generate exploration options with `generate_image`.
4. **Set usage rules.** How the logo may/may not be used, spacing, do's and don'ts. Rules are what keep
   the brand consistent when many agents produce assets.
5. **Assemble the kit.** One reference the whole fleet uses: voice + visuals + rules + example assets.
   `save_file` and `update_company_playbook` so every role pulls from the same source.
6. **Govern consistency.** `write_memory` (type `learning`) the core identity; downstream skills
   (`social-graphics-batch`, `pitch-deck-design`, `blog-post-production`) must reference this kit, not reinvent.

## Decision framework — distinctive but consistent
Prefer a simple, distinctive identity applied consistently over an elaborate one applied loosely.
Consistency compounds recognition; a brand that looks different every time builds none.

## Definition of done
- Rooted in positioning; verbal and visual identity defined with usage rules and examples.
- Assembled into one kit in the playbook that all asset-producing skills reference.

## Common failure modes
- **Decoration without strategy.** A pretty brand that doesn't reinforce the positioning.
- **No usage rules.** Without rules, many producers = many inconsistent looks.
- **Living in one head.** If it's not in the playbook, every asset improvises.
