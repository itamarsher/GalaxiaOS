---
name: regulatory-landscape-scan
title: Regulatory Landscape Scan
description: Map the regulations and compliance obligations that apply to the business before they become problems.
roles: research, governance, ceo
---
# Regulatory Landscape Scan

Regulation ignored becomes an existential risk. This playbook maps the rules that apply to the
business and its plans — early, so compliance is designed in, not bolted on after a violation.

## Workflow
1. **Scope by business model and geography.** Which domains apply — data privacy (GDPR/CCPA),
   payments, industry-specific (health, finance), marketing/consumer, employment? Scope depends on
   what we do, where, and to whom. `web_search` for the applicable regimes.
2. **Identify concrete obligations.** For each applicable area, list the specific obligations (consent,
   disclosures, data handling, licensing). Vague awareness isn't compliance; specifics are.
3. **Assess current gaps.** Compare obligations to what the company actually does today
   (`list_data_policies`, `check_compliance`). `flag_legal_risk` on any gap with real exposure.
4. **Prioritize by risk.** Rank gaps by likelihood × severity (fines, shutdown, reputational). Not
   all obligations carry equal risk; focus effort where exposure is greatest.
5. **Know your limits.** This is a scan, not legal advice. For material or ambiguous obligations,
   `request_user_action` to involve qualified counsel — don't have an agent adjudicate real legal risk.
6. **Report and monitor.** `create_report` (kind `research_report`) with the landscape, gaps, and
   priorities; make it recurring — regulation changes, and so does what the company does.

## Decision framework — design in, don't bolt on
Address high-risk obligations before they gate a launch (`product-launch-checklist`). Retrofitting
compliance after a violation costs far more than building it in.

## Definition of done
- Applicable regimes scoped by model/geography; concrete obligations listed; gaps assessed and risk-ranked.
- Material/ambiguous items escalated to counsel; landscape reported and made recurring.

## Common failure modes
- **Vague awareness.** Knowing "GDPR exists" isn't knowing your obligations under it.
- **Agent-as-lawyer.** Real legal calls need qualified counsel; escalate them.
- **One-and-done.** Regulation and the business both change; scan on a cadence.
