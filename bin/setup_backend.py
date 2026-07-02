#!/usr/bin/env python3
"""Provision the DynamoDB order table behind gateway/order_lambda/lambda_function.py,
seed it from seed/orders.json, and (if BeaconMemory has been deployed) seed a few
memory priors from seed/memory_priors.md.

Needs boto3 on the PATH's Python. Either run inside app/beacon's venv, or:

    uv run --with boto3 python bin/setup_backend.py

Idempotent — re-running reuses the existing table (matched by name) instead of
failing, and re-seeding just overwrites items by order_id.

    export AWS_PROFILE=your-profile
    export AWS_REGION=us-west-2
    python bin/setup_backend.py

What it does:
  1. Creates DynamoDB table BEACON_ORDERS_TABLE (default "beacon-orders"): on-demand
     billing, partition key order_id (S), GSI "customer_email-index" (partition key
     customer_email, S) — the exact shape gateway/order_lambda/lambda_function.py
     expects.
  2. Batch-writes seed/orders.json into it.
  3. If MEMORY_BEACONMEMORY_ID is set (i.e. `agentcore add memory` + `agentcore
     deploy` already ran for BeaconMemory), seeds seed/memory_priors.md's notes into
     AgentCore Memory via MemoryClient.create_event. If not set, skips that step with
     a clear message rather than failing — there's no local fallback for Memory.
"""

from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[1]
SEED = REPO / "seed"

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("BEACON_ORDERS_TABLE", "beacon-orders")
MEMORY_ID = os.environ.get("MEMORY_BEACONMEMORY_ID")


# --- DynamoDB table -----------------------------------------------------------
def setup_table(session) -> None:
    ddb = session.client("dynamodb")
    try:
        ddb.describe_table(TableName=TABLE_NAME)
        print(f"  reusing table {TABLE_NAME}")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    try:
        ddb.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "order_id", "AttributeType": "S"},
                {"AttributeName": "customer_email", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "order_id", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "customer_email-index",
                    "KeySchema": [{"AttributeName": "customer_email", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise
        print(f"  table {TABLE_NAME} already being created, waiting for ACTIVE")

    print(f"  created table {TABLE_NAME}, waiting for ACTIVE...")
    ddb.get_waiter("table_exists").wait(TableName=TABLE_NAME)
    print(f"  table {TABLE_NAME} is ACTIVE")


# --- seed orders ---------------------------------------------------------------
def seed_orders(session) -> int:
    orders = json.loads((SEED / "orders.json").read_text())
    # DynamoDB's resource API needs Decimal, not float, for numeric attributes.
    orders = json.loads(json.dumps(orders), parse_float=Decimal)
    table = session.resource("dynamodb").Table(TABLE_NAME)
    with table.batch_writer(overwrite_by_pkeys=["order_id"]) as batch:
        for order in orders:
            batch.put_item(Item=order)
    print(f"  seeded {len(orders)} orders into {TABLE_NAME}")
    return len(orders)


# --- memory priors --------------------------------------------------------------
def parse_memory_priors() -> list[tuple[str, str, str]]:
    """Parse seed/memory_priors.md's '## <email> — <TYPE>' sections.

    Returns a list of (actor_id, memory_type, text).
    """
    md = (SEED / "memory_priors.md").read_text()
    parts = re.split(r"(?m)^## (.+)$", md)[1:]  # [header, body, header, body, ...]
    notes = []
    for header, body in zip(parts[0::2], parts[1::2]):
        email, _, mtype = header.partition("—")
        notes.append((email.strip(), mtype.strip(), body.strip()))
    return notes


def seed_memory() -> int:
    if not MEMORY_ID:
        print("Memory not deployed yet — skipping memory seeding. Run after `agentcore deploy`.")
        return 0

    from bedrock_agentcore.memory import MemoryClient

    client = MemoryClient(region_name=REGION)
    notes = parse_memory_priors()
    for actor_id, mtype, text in notes:
        client.create_event(
            memory_id=MEMORY_ID,
            actor_id=actor_id,
            session_id="seed",
            messages=[(text, "ASSISTANT")],
            metadata={
                "source": {"stringValue": "seed/memory_priors.md"},
                "memoryType": {"stringValue": mtype},
            },
        )
        print(f"  seeded {mtype} note for {actor_id}")
    return len(notes)


def main() -> None:
    session = boto3.Session(region_name=REGION)
    try:
        ident = session.client("sts").get_caller_identity()
    except Exception as e:
        raise SystemExit(f"No AWS credentials. Run `export AWS_PROFILE=...` first. ({e})")
    print(f"── account {ident['Account']} · region {REGION} ──\n")

    print("── DynamoDB table ───────────────────────────")
    setup_table(session)

    print("\n── seed orders ──────────────────────────────")
    order_count = seed_orders(session)

    print("\n── seed AgentCore Memory ────────────────────")
    memory_count = seed_memory()

    print("\n✓ setup complete.")
    print(f"  table:   {TABLE_NAME}")
    print(f"  orders:  {order_count} seeded")
    print(f"  memory:  {memory_count} note(s) seeded" if memory_count else "  memory:  skipped")
    print("\nNext: bin/deploy_order_lambda.py, then `agentcore deploy`.")


if __name__ == "__main__":
    main()
