---
name: legal-risk-flagging
title: Legal Risk Flagging
description: Recognize when an action carries real legal risk and route it to human counsel instead of guessing.
roles: governance, ceo
---
# Legal Risk Flagging

The fleet acts fast and mostly without lawyers — so recognizing when something carries real legal risk, and
stopping to route it, is a core safeguard. This playbook is that tripwire.

## Workflow
1. **Scan for the risk categories.** Contracts and unusual terms (liability, IP, indemnity, exclusivity),
   regulated claims, personal data, employment, trademark/IP conflicts, and anything involving real money or
   irreversible commitment. These are the domains where a wrong move is expensive.
2. **Judge materiality.** Is the potential harm material (real financial, legal, or reputational exposure) or
   trivial? Not everything needs a lawyer, but err toward flagging — the fleet's risk is under-flagging, not over.
3. **Flag it.** `flag_legal_risk` with the specific concern and why it matters. A clear flag with context is
   far more useful than a vague worry or silent proceed.
4. **Stop before the irreversible step.** If the risk is material, do NOT complete the action (sign, send,
   publish, pay) on the fleet's own judgment. Halt at the tripwire; an agent must not adjudicate real legal risk.
5. **Route to a human.** `request_user_action` / `request_decision` to bring in the founder and, where needed,
   qualified counsel. Give them the specifics so they can decide efficiently (`founder-decision-brief`).
6. **Record.** `write_memory` (type `learning`) the flag and its resolution, so the fleet learns which
   situations warrant flagging and doesn't repeat near-misses.

## Decision framework — when unsure, flag and stop
The asymmetry is decisive: flagging a non-issue costs a little time; missing a real legal risk can cost the
company. When in genuine doubt about material legal exposure, the correct action is always flag, stop, and escalate.

## Definition of done
- Action scanned against the legal-risk categories; materiality judged with a bias toward flagging.
- Material risks flagged with specifics; irreversible step halted; routed to founder/counsel; recorded.

## Common failure modes
- **Silent proceed.** Completing a legally risky action on an agent's own judgment.
- **Vague flags.** "This seems risky" without the specific concern wastes the human's time.
- **Under-flagging.** Treating material exposure as trivial to avoid friction.
