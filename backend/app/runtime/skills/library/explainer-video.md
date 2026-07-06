---
name: explainer-video
title: Explainer Video
description: Produce a short explainer video that makes the product's value clear in under a minute.
roles: design, growth
---
# Explainer Video

A good explainer makes someone 'get it' fast. This playbook produces a short, clear video that lands
the value in under a minute — scripted around the viewer's problem, not a feature tour.

## Workflow
1. **Define the one takeaway.** After watching, the viewer should understand one thing (usually: what
   problem this solves for them). Everything serves that. `write_memory` (type `experiment`) the takeaway
   and where the video will run.
2. **Script problem-first.** Open with the viewer's pain, then the solution, then the proof/CTA. Lead
   with the product and you lose them; lead with their problem and they lean in. Keep it tight — every
   second must earn its place.
3. **Storyboard.** Map script to visuals scene by scene before producing. Cheap to change on paper,
   expensive to change in production.
4. **Produce on-brand.** `generate_video` / `generate_image` for scenes, guided by `brand-identity-kit`.
   Clear audio and legible text matter more than fancy effects — comprehension first.
5. **Keep it short and captioned.** Aim under 60–90 seconds; most viewers watch muted, so caption it.
   A concise, captioned video outperforms a long, audio-dependent one.
6. **Publish and measure.** `publish_content` / `schedule_social_post`; `record_metric` for view-through
   and conversion; `write_memory` (type `learning`) what hook and length worked.

## Decision framework — clarity over production value
Optimize for the viewer understanding fast, not for cinematic polish. A plain, clear explainer beats a
beautiful, confusing one. If a scene doesn't advance understanding, cut it.

## Definition of done
- One takeaway defined; problem-first script; storyboarded before production; on-brand.
- Short and captioned; published and measured; winning hook/length recorded.

## Common failure modes
- **Feature tour.** Leading with the product instead of the viewer's problem.
- **Too long.** Attention drops fast; if it's over ~90s, cut.
- **Audio-dependent.** No captions means muted viewers get nothing.
