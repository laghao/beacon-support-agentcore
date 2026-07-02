#!/usr/bin/env python3
"""Zip and deploy gateway/order_lambda/lambda_function.py as a plain Lambda function.

Deliberately plain boto3, no SAM/CDK: agentcore.json's OrderRefundLookup gateway
target only stores the Lambda's ARN as a reference (lambdaFunctionArn.lambdaArn) —
the CLI's resource model doesn't build or own that Lambda's code, so this script is
the simplest path to a working ARN to paste in.

Needs boto3 on the PATH's Python. Either run inside app/beacon's venv, or:

    uv run --with boto3 python bin/deploy_order_lambda.py

Idempotent: creates the IAM role + function if missing, otherwise updates the
function's code/config in place.

    export AWS_PROFILE=your-profile
    export AWS_REGION=us-west-2
    python bin/deploy_order_lambda.py
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[1]
LAMBDA_SRC = REPO / "gateway" / "order_lambda" / "lambda_function.py"

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("BEACON_ORDERS_TABLE", "beacon-orders")
ROLE_NAME = "BeaconOrderLambdaRole"
FUNCTION_NAME = "beacon-order-lambda"
INLINE_POLICY_NAME = "BeaconOrderLambdaInline"

TRUST_POLICY = {
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }
    ],
}


def zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(LAMBDA_SRC, arcname="lambda_function.py")
    return buf.getvalue()


def setup_role(session, account_id: str) -> str:
    iam = session.client("iam")
    try:
        role = iam.get_role(RoleName=ROLE_NAME)
        print(f"  reusing IAM role {ROLE_NAME}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        role = iam.create_role(RoleName=ROLE_NAME, AssumeRolePolicyDocument=json.dumps(TRUST_POLICY))
        print(f"  created IAM role {ROLE_NAME}")

    table_arn = f"arn:aws:dynamodb:{REGION}:{account_id}:table/{TABLE_NAME}"
    inline_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": "*",
            },
            {
                "Effect": "Allow",
                "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:BatchWriteItem"],
                "Resource": [table_arn, f"{table_arn}/index/*"],
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME, PolicyName=INLINE_POLICY_NAME, PolicyDocument=json.dumps(inline_policy)
    )
    return role["Role"]["Arn"]


def setup_function(session, role_arn: str) -> str:
    lam = session.client("lambda")
    code = zip_bytes()
    env = {"Variables": {"BEACON_ORDERS_TABLE": TABLE_NAME}}

    try:
        lam.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        exists = False

    if exists:
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=code)
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        lam.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Handler="lambda_function.handler",
            Runtime="python3.12",
            Environment=env,
            Role=role_arn,
        )
        lam.get_waiter("function_updated_v2").wait(FunctionName=FUNCTION_NAME)
        print(f"  updated function {FUNCTION_NAME}")
    else:
        # A freshly created IAM role can take a few seconds to propagate to Lambda;
        # retry create_function briefly instead of failing on the first attempt.
        last_err = None
        for _ in range(6):
            try:
                lam.create_function(
                    FunctionName=FUNCTION_NAME,
                    Runtime="python3.12",
                    Role=role_arn,
                    Handler="lambda_function.handler",
                    Code={"ZipFile": code},
                    Environment=env,
                    Timeout=15,
                    MemorySize=256,
                )
                last_err = None
                break
            except ClientError as e:
                last_err = e
                if e.response["Error"]["Code"] == "InvalidParameterValueException":
                    time.sleep(5)
                    continue
                raise
        if last_err:
            raise last_err
        lam.get_waiter("function_active_v2").wait(FunctionName=FUNCTION_NAME)
        print(f"  created function {FUNCTION_NAME}")

    return lam.get_function(FunctionName=FUNCTION_NAME)["Configuration"]["FunctionArn"]


def main() -> None:
    session = boto3.Session(region_name=REGION)
    try:
        account_id = session.client("sts").get_caller_identity()["Account"]
    except Exception as e:
        raise SystemExit(f"No AWS credentials. Run `export AWS_PROFILE=...` first. ({e})")
    print(f"── account {account_id} · region {REGION} ──\n")

    print("── IAM role ──────────────────────────────────")
    role_arn = setup_role(session, account_id)
    print(f"  role arn: {role_arn}")

    print("\n── Lambda function ───────────────────────────")
    fn_arn = setup_function(session, role_arn)

    print(f"\n✓ Lambda ready: {fn_arn}")
    print("\nPaste this ARN into agentcore/agentcore.json's OrderRefundLookup target's")
    print("lambdaArn field (currently a placeholder), then run `agentcore deploy`.")


if __name__ == "__main__":
    main()
