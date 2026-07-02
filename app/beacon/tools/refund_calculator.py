"""Sandboxed refund math via AgentCore Code Interpreter (row 8 of the capability table).

Refund math is exactly the kind of thing you don't want an LLM doing in its head:
it's arithmetic, it should be auditable, and a bug should show up as a sandbox
stack trace, not a hallucinated dollar figure. Every call here runs a short
Python snippet in a fresh microVM and returns whatever the snippet printed.
"""

import json
import logging
import os

from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands import tool

logger = logging.getLogger(__name__)

REGION = os.getenv("AWS_REGION", "us-west-2")


def _extract_stdout(result: dict) -> str:
    """Pull the printed text out of a code_session().invoke() response."""
    chunks = []
    for event in result.get("stream", []):
        for item in event.get("result", {}).get("content", []):
            if item.get("type") == "text" and item.get("text"):
                chunks.append(item["text"])
    return "\n".join(chunks)


REFUND_CODE_TEMPLATE = """
import json

order_total = {order_total_usd}
returned_value = {items_returned_value_usd}
days_since_delivery = {days_since_delivery}
restocking_fee_pct = {restocking_fee_pct}

# Northwind Outfitters refund policy — see skills/refund-policy.md.
# Assumes the caller already ran check_return_eligibility (Gateway/Lambda tool);
# this sandbox only computes the dollar amount, it does not re-decide eligibility.
eligible = days_since_delivery <= 30
fee = round(returned_value * restocking_fee_pct, 2) if days_since_delivery > 14 else 0.0
refund_amount = round(max(returned_value - fee, 0.0), 2) if eligible else 0.0

print(json.dumps({{
    "eligible": eligible,
    "returned_value_usd": round(returned_value, 2),
    "restocking_fee_usd": fee,
    "refund_amount_usd": refund_amount,
}}))
"""


@tool
def calculate_refund(
    order_total_usd: float,
    items_returned_value_usd: float,
    days_since_delivery: int,
    restocking_fee_pct: float = 0.0,
) -> str:
    """Compute a refund amount in an isolated AgentCore Code Interpreter sandbox.

    Args:
        order_total_usd: The original order total, for context/logging.
        items_returned_value_usd: Dollar value of the item(s) being returned.
        days_since_delivery: Days between delivery and the return request.
        restocking_fee_pct: Restocking fee as a fraction (0.15 = 15%). Northwind
            only applies this beyond the 14-day no-fee window; pass 0 for
            defective/wrong-item returns, which never carry a fee.

    Returns:
        JSON string: eligible, returned_value_usd, restocking_fee_usd, refund_amount_usd.
    """
    code = REFUND_CODE_TEMPLATE.format(
        order_total_usd=order_total_usd,
        items_returned_value_usd=items_returned_value_usd,
        days_since_delivery=days_since_delivery,
        restocking_fee_pct=restocking_fee_pct,
    )
    try:
        with code_session(REGION) as client:
            result = client.invoke("executeCode", {"code": code, "language": "python"})
    except Exception as e:
        logger.error("Code Interpreter session failed: %s", e)
        return json.dumps({"error": f"AGENTCORE_ERROR: refund sandbox unavailable ({e})"})

    stdout = _extract_stdout(result)
    try:
        return json.dumps(json.loads(stdout.strip().splitlines()[-1]))
    except (ValueError, IndexError):
        return json.dumps({"error": "AGENTCORE_ERROR: sandbox returned no parseable output", "raw": stdout})
