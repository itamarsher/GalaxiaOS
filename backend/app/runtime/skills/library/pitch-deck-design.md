---
name: pitch-deck-design
title: Pitch Deck Design
description: Design a fundraising or sales pitch deck that carries a clear narrative and honest, legible data.
roles: design, ceo, finance
---
# Pitch Deck Design

A deck is a narrative device, not a document. This playbook designs one that carries the story
clearly and presents real data legibly — supporting the pitch, not substituting for it.

## Workflow
1. **Start from the narrative, not slides.** Pull the story and real content from `fundraising-prep`
   (or the sales case). Design serves the argument: problem → why now → solution → traction → market →
   team → ask. Nail the sequence before styling.
2. **One idea per slide.** Each slide makes a single point, stated in the headline. If the audience must
   read a paragraph to get it, it's too dense — cut or split.
3. **Make data honest and legible.** Charts must show real numbers clearly, with axes and context — no
   truncated axes or cherry-picked ranges that mislead. A deck caught inflating loses the room.
4. **Apply the brand.** Consistent visual identity from `brand-identity-kit`; clean, uncluttered layout.
   Generate supporting visuals with `generate_image`. Polish signals competence, but substance carries it.
5. **Design for the medium.** A sent deck needs more on-slide context; a presented deck should be sparse
   so the presenter is the focus. Know which you're building.
6. **Deliver and iterate.** `save_file`; `write_memory` (type `learning`) which slides raise questions
   or objections (from `fundraising-prep` tracking) and refine them.

## Decision framework — story over decoration
Every design choice should make the argument clearer. Flashy visuals that obscure the point hurt; a
plain slide that lands the point wins. The deck's job is comprehension, then confidence.

## Definition of done
- Built on a clear narrative sequence; one honest idea per slide; data legible and non-misleading.
- On-brand and medium-appropriate; delivered, with objection-raising slides refined.

## Common failure modes
- **Slides before story.** Designing pages before the argument is settled.
- **Misleading charts.** Truncated axes or cherry-picked data destroy credibility.
- **Dense slides.** Paragraphs the audience must read instead of a point they instantly get.
