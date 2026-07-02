"""Lambda behind BeaconGateway's OrderRefundLookup target (lambda-function-arn).

Registered via:
  agentcore add gateway-target --name OrderRefundLookup --gateway BeaconGateway \\
    --type lambda-function-arn --lambda-arn <this function's ARN> \\
    --tool-schema-file gateway/order_lambda/tool-schema.json

AgentCore Gateway invokes this function once per tool call and passes the tool
name via the Lambda client context (`bedrockAgentCoreToolName`, optionally
prefixed with the gateway target name and "___" — both forms are handled
below). `event` is the tool's arguments exactly as declared in tool-schema.json.

Data lives in a DynamoDB table (BEACON_ORDERS_TABLE), seeded by
bin/setup_backend.py — the mock order/CRM database this Lambda is a thin
read/write layer over. Nothing here is provisioned by `agentcore add`; that's
the point of keeping it in gateway/ + bin/ instead of the agentcore/ tree.
"""

import json
import os
from datetime import date, datetime

import boto3

TABLE_NAME = os.environ.get("BEACON_ORDERS_TABLE", "beacon-orders")
_dynamodb = boto3.resource("dynamodb")
_table = _dynamodb.Table(TABLE_NAME)

RETURN_WINDOW_DAYS = 30
NO_FEE_WINDOW_DAYS = 14
RESTOCKING_FEE_PCT = 0.15


def _tool_name(event: dict, context) -> str:
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    name = custom.get("bedrockAgentCoreToolName") or event.get("bedrockToolName", "")
    return name.split("___")[-1] if name else event.get("__tool_name__", "")


def _get_order(order_id: str) -> dict | None:
    resp = _table.get_item(Key={"order_id": order_id})
    return resp.get("Item")


def get_order_status(event: dict) -> dict:
    order = _get_order(event["order_id"])
    if not order:
        return {"error": f"No order found with id {event['order_id']}"}
    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "carrier": order.get("carrier", ""),
        "tracking_number": order.get("tracking_number", ""),
        "estimated_delivery": order.get("estimated_delivery", ""),
        "last_update": order.get("last_update", ""),
    }


def get_order_details(event: dict) -> dict:
    order = _get_order(event["order_id"])
    if not order:
        return {"error": f"No order found with id {event['order_id']}"}
    return {
        "order_id": order["order_id"],
        "customer_email": order.get("customer_email", ""),
        "order_date": order.get("order_date", ""),
        "total_usd": float(order.get("total_usd", 0)),
        "items": order.get("items", []),
        "shipping_address": order.get("shipping_address", ""),
    }


def check_return_eligibility(event: dict) -> dict:
    order = _get_order(event["order_id"])
    if not order:
        return {"error": f"No order found with id {event['order_id']}"}

    item_sku = event.get("item_sku")
    if item_sku:
        item = next((i for i in order.get("items", []) if i.get("sku") == item_sku), None)
        if item and item.get("final_sale"):
            return {
                "order_id": order["order_id"],
                "eligible": False,
                "reason": f"{item_sku} is marked final sale.",
                "return_window_closes_on": "",
                "days_remaining": 0,
            }

    if order.get("defective_or_wrong_item"):
        return {
            "order_id": order["order_id"],
            "eligible": True,
            "reason": "Reported as defective/wrong item — no return-window limit applies.",
            "return_window_closes_on": "",
            "days_remaining": 90,
        }

    delivered_at = order.get("delivered_at")
    if not delivered_at:
        return {
            "order_id": order["order_id"],
            "eligible": False,
            "reason": "Order has not been marked delivered yet.",
            "return_window_closes_on": "",
            "days_remaining": 0,
        }

    delivered_date = datetime.strptime(delivered_at, "%Y-%m-%d").date()
    days_since_delivery = (date.today() - delivered_date).days
    closes_on = delivered_date.fromordinal(delivered_date.toordinal() + RETURN_WINDOW_DAYS)
    days_remaining = max(RETURN_WINDOW_DAYS - days_since_delivery, 0)
    eligible = days_since_delivery <= RETURN_WINDOW_DAYS

    return {
        "order_id": order["order_id"],
        "eligible": eligible,
        "reason": "Within the 30-day return window." if eligible else "Outside the 30-day return window.",
        "return_window_closes_on": closes_on.isoformat(),
        "days_remaining": days_remaining,
    }


def list_customer_orders(event: dict) -> dict:
    resp = _table.query(
        IndexName="customer_email-index",
        KeyConditionExpression=boto3.dynamodb.conditions.Key("customer_email").eq(event["customer_email"]),
    )
    orders = [
        {
            "order_id": item["order_id"],
            "order_date": item.get("order_date", ""),
            "status": item.get("status", ""),
            "total_usd": float(item.get("total_usd", 0)),
        }
        for item in resp.get("Items", [])
    ]
    return {"orders": orders}


_HANDLERS = {
    "get_order_status": get_order_status,
    "get_order_details": get_order_details,
    "check_return_eligibility": check_return_eligibility,
    "list_customer_orders": list_customer_orders,
}


def handler(event, context):
    tool_name = _tool_name(event, context)
    fn = _HANDLERS.get(tool_name)
    if not fn:
        return {"error": f"Unknown tool '{tool_name}'. Expected one of: {', '.join(_HANDLERS)}"}
    try:
        return fn(event)
    except Exception as e:  # noqa: BLE001 - surface as a tool error, not a Lambda failure
        return {"error": f"{tool_name} failed: {e}"}


if __name__ == "__main__":
    print(json.dumps(get_order_status({"order_id": "NW-10042"}), indent=2))
