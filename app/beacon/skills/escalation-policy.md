# Skill: escalation-policy

Use this to decide whether a session needs `escalate_to_human`.

## Always escalate
- Any mention of fraud, unauthorized charge, or a stolen package the customer wants investigated as theft (not just a delayed shipment).
- A refund request above $500, or above a specialist's authority (Billing may approve up to $500 unassisted).
- Legal language: "lawyer", "chargeback", "BBB complaint", "sue".
- Safety complaints about a product (injury, chemical smell, fire hazard).

## Escalate after one failed attempt, not zero
For an upset-but-not-yet-escalation-worthy customer, try one genuine resolution attempt first (with the tone from tone-guide.md). If the next message is still angry or repeats the same demand, escalate — don't cycle through more attempts hoping the third one lands.

## What NOT to escalate
- A customer who is simply asking "why is this late" — that's Shipping's known-issue triage, not an escalation.
- A return outside the window where the answer is just "no, and here's why" stated clearly and once.

## How to escalate
Call `escalate_to_human(reason=...)` with one sentence a human agent can act on without re-reading the whole conversation: what happened, what the customer wants, and why it's above what you can resolve.
