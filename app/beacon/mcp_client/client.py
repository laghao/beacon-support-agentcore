"""MCP client for BeaconGateway — the Lambda (order/refund) and OpenAPI (carrier
status) targets wired up via `agentcore add gateway` / `agentcore add gateway-target`
in agentcore/agentcore.json. Specialist agents get these as ordinary Strands
tools; nobody hand-writes an order-lookup or carrier-status tool function —
Gateway derives them from the Lambda's tool-schema.json and the OpenAPI spec.

GATEWAY_BEACONGATEWAY_URL / _AUTH_TYPE are injected by CDK for in-project
resources (see agentcore/cdk's wire-connections.js: `GATEWAY_${token}_URL`).
"""

import logging
import os
from typing import Optional

from mcp.client.streamable_http import streamablehttp_client
from strands.tools.mcp.mcp_client import MCPClient

logger = logging.getLogger(__name__)

GATEWAY_URL = os.getenv("GATEWAY_BEACONGATEWAY_URL")
GATEWAY_AUTH_TYPE = os.getenv("GATEWAY_BEACONGATEWAY_AUTH_TYPE", "NONE")


def get_beacon_gateway_mcp_client() -> Optional[MCPClient]:
    """Returns an MCP client for BeaconGateway, or None if it isn't deployed yet.

    BeaconGateway's authorizerType is NONE (see agentcore.json) — no bearer
    token or SigV4 signing needed here. A gateway configured with AWS_IAM would
    need SigV4-signed requests; CUSTOM_JWT would need an `Authorization: Bearer
    <token>` header sourced from your identity provider.
    """
    if not GATEWAY_URL:
        logger.warning("GATEWAY_BEACONGATEWAY_URL not set — deploy BeaconGateway first (agentcore deploy).")
        return None

    return MCPClient(lambda: streamablehttp_client(GATEWAY_URL))
