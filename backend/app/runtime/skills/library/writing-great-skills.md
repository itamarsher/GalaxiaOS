---
name: writing-great-skills
title: Writing Great Skills
description: Author or audit a skill playbook against a shared rubric so the library stays sharp, small, and trusted as it grows.
roles: ceo, governance
---
# Writing Great Skills

A library is only as good as its worst playbook — bloated, stale, or never-triggered skills tax every
agent that carries them. This is the shared rubric for writing a new skill or auditing an existing one,
in four passes: trigger, structure, steering, pruning.

## When to use
- You are adding a skill to `library/`, or a retrospective flagged one as bloated, stale, or ignored.

## Workflow
1. **Trigger — the description is the switch.** Skills here are model-invoked: the one-line `description`
   is all an agent sees when deciding to `load_skill`, so write it as the *situation that should fire it*,
   not a restated title. Then pay the **context load** — each description sits in the index of every agent
   its `roles` reach, on every request — so scope `roles` to exactly who calls it, never wider.
2. **Structure — steps and reference.** A skill is two units: **steps** (the `Workflow`) and **reference**
   (the `Decision framework`, templates, definitions that support them). Name which you're writing; a
   pure-reference skill needs no fake steps, a pure-procedure skill no padding.
3. **Keep the body small.** The whole body loads on every use — there is no external-file split in this
   loader — so carry only what the common path needs, not material that serves one rare branch.
4. **Steering — coin a leading word.** For the behavior you want, coin one loaded phrase and repeat it
   across the steps, framework, and failure modes — the way this library leans on `altitude`, `reserve
   before you commit`, `Fit is a gate`. It has landed when the phrase echoes back in the agent's reasoning.
   If a step keeps getting shortchanged because the agent races to the deliverable (classic: clarifying
   questions before the doc), split that phase into its own skill and hand it off with `dispatch_task`.
5. **Prune — run the deletion test.** Delete each sentence and ask if behavior changes; if not, it's a
   **no-op** — cut it. One source of truth per fact; sweep out **sediment**, lines that no longer serve the
   steps. Finish with a `Definition of done` and `Common failure modes`.

## Decision framework — one job, said small
A great skill does one job and says it in the fewest words that still steer. When torn between adding a
clause and cutting one, cut — an unread skill and an over-stuffed skill fail the same way, by not being
followed. Precision in the trigger and the leading word buys more than volume ever will.

## Definition of done
- Description names the firing situation; `roles` scoped to actual users; steps vs. reference is deliberate.
- A leading word carries the key behavior; body survives the deletion test; DoD and failure modes present.

## Common failure modes
- **Description restates the title.** The trigger never fires because it names the skill, not the moment.
- **Broad roles / bloated body.** Context load on agents who never call it; every caller pays for rare branches.
- **No-ops and sediment.** Paragraphs that read well but change nothing, and stale lines no one dares delete.
