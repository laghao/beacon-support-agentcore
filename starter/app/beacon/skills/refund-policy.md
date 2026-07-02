# Skill: refund-policy

Use this when deciding whether a return is eligible and what it should refund.

## Return window
- Full eligibility: within 30 days of delivery (not order date).
- Defective or wrong-item shipped: eligible any time within 90 days, no restocking fee, no exceptions below apply.
- Beyond 30 days (non-defective): not eligible. Say so plainly; don't offer a workaround.

## Restocking fee
- No fee for returns made within 14 days of delivery.
- 15% restocking fee for returns made 15-30 days after delivery, unless the item is defective/wrong-item.
- Never apply a restocking fee to store credit exchanges (item-for-item swap).

## How to answer a refund question
1. Call `check_return_eligibility` (Gateway/Lambda tool) first — it knows the order's actual delivery date.
2. If eligible, call `calculate_refund` (Code Interpreter tool) to get the exact dollar amount. Don't do the arithmetic yourself.
3. State the refund amount and the restocking fee separately if one applied — customers push back less on a fee they can see than one folded into a smaller total.

## Final-sale items
Items tagged "final sale" in the order are never refund-eligible regardless of days elapsed. `check_return_eligibility` already accounts for this — trust its `eligible` field over your own read of the days-since-delivery number.
