# Skill: known-issues-triage

Use this when a customer reports a tracking problem ("hasn't updated in N days", "stuck in transit") before assuming it's specific to their order.

## Triage order
1. Call `check_carrier_service_alerts(carrier)` (Browser tool) — if the carrier has an active regional service disruption, that's almost always the explanation, not a lost package.
2. If no active alert, call `get_order_status` (Gateway/Lambda tool) for the order's own tracking history.
3. Only after both come back clean should you treat this as a possible lost-package case and consider `escalate_to_human`.

## How to phrase a known-issue match
State the carrier disruption plainly and give a revised expectation ("UPS is reporting weather delays in your region; expect 2-3 extra days") rather than a vague "please wait a bit longer" — the second one reads as a brush-off even when it's accurate.

## When it's NOT a known issue
If carrier alerts are clean and the order's own status hasn't moved in more than 5 days, treat it as a genuine exception — this is a real trigger for escalation-policy.md's fraud/theft branch if the customer suspects the package was stolen, or a plain Shipping escalation otherwise.
