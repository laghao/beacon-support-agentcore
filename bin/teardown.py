#!/usr/bin/env python3
"""Delete what bin/setup_backend.py and bin/deploy_order_lambda.py created.

Needs boto3 on the PATH's Python. Either run inside app/beacon's venv, or:

    uv run --with boto3 python bin/teardown.py

    export AWS_PROFILE=your-profile
    python bin/teardown.py            # prompts before deleting
    python bin/teardown.py --yes      # no prompt

Removes: the beacon-orders DynamoDB table, the beacon-order-lambda function, and
its BeaconOrderLambdaRole IAM role. AgentCore-managed resources (Runtime, Gateway,
Memory) are left alone — those belong to `agentcore remove` / the console, not this
script, since `agentcore` doesn't know about the resources this repo's bin/ scripts
provision either.
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("BEACON_ORDERS_TABLE", "beacon-orders")
ROLE_NAME = "BeaconOrderLambdaRole"
FUNCTION_NAME = "beacon-order-lambda"
INLINE_POLICY_NAME = "BeaconOrderLambdaInline"


def main() -> None:
    if "--yes" not in sys.argv:
        ans = (
            input(
                f"Delete DynamoDB table '{TABLE_NAME}', Lambda '{FUNCTION_NAME}', "
                f"and IAM role '{ROLE_NAME}'? [y/N] "
            )
            .strip()
            .lower()
        )
        if ans not in ("y", "yes"):
            print("aborted.")
            return

    session = boto3.Session(region_name=REGION)

    ddb = session.client("dynamodb")
    try:
        ddb.delete_table(TableName=TABLE_NAME)
        print(f"✓ deleted DynamoDB table {TABLE_NAME}")
    except ClientError as e:
        print(f"⚠ table: {e.response['Error']['Code']}")

    lam = session.client("lambda")
    try:
        lam.delete_function(FunctionName=FUNCTION_NAME)
        print(f"✓ deleted Lambda function {FUNCTION_NAME}")
    except ClientError as e:
        print(f"⚠ lambda: {e.response['Error']['Code']}")

    iam = session.client("iam")
    try:
        iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName=INLINE_POLICY_NAME)
    except ClientError:
        pass  # role or policy may already be gone; delete_role below reports that
    try:
        iam.delete_role(RoleName=ROLE_NAME)
        print(f"✓ deleted IAM role {ROLE_NAME}")
    except ClientError as e:
        print(f"⚠ IAM role: {e.response['Error']['Code']}")

    print("\nDone. AgentCore-managed resources (Runtime/Gateway/Memory) are untouched —")
    print("use `agentcore remove` or the AWS console for those.")


if __name__ == "__main__":
    main()
