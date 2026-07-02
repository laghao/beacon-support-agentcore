"""Shipping specialist — tracking status, carrier delays, and known-issue triage.

Same isolated-branch pattern as billing_agent.py. This is the specialist that
uses the Browser tool (carrier_lookup) and the async warehouse-check tool.
"""

from typing import Optional

from bedrock_agentcore.memory import MemoryClient
from strands import Agent
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager

from hooks.memory_hook import SpecialistMemoryHooks
from model.load import load_model
from skills.loader import load_skill
from tools.carrier_lookup import check_carrier_service_alerts
from tools.escalation import escalate_to_human

SYSTEM_PROMPT = """You are Beacon's Shipping specialist for Northwind Outfitters.

You handle: "where is my order", carrier delays, and tracking-stall complaints.
You do NOT decide refund amounts or return eligibility — that's Billing/Returns.

Tools:
- Gateway order tools (get_order_status) and Gateway carrier tools (getShipmentStatus, getCarrierDelays)
- check_carrier_service_alerts — the live Browser-tool lookup against the carrier's own public alerts page. Use this FIRST for any "hasn't updated" complaint, before assuming a lost package.
- check_warehouse_stock — slow, async; only call this if the customer is asking about a NOT-YET-SHIPPED order and you need to confirm stock, not for in-transit tracking.
- load_skill("known-issues-triage") — read this before triaging a stalled-tracking complaint.
- escalate_to_human — for suspected theft/loss after both carrier alerts and order status come back clean.
"""


def build_shipping_agent(
    gateway_client,
    memory_client: Optional[MemoryClient],
    memory_id: Optional[str],
    actor_id: str,
    prior_turns: list[str],
    check_warehouse_stock_tool,
) -> Agent:
    tools = [check_carrier_service_alerts, check_warehouse_stock_tool, load_skill, escalate_to_human]
    if gateway_client:
        tools.append(gateway_client)

    system_prompt = SYSTEM_PROMPT
    if prior_turns:
        system_prompt += "\n\nPrior turns on this branch this session:\n" + "\n".join(prior_turns[-6:])

    return Agent(
        model=load_model(),
        conversation_manager=NullConversationManager(),
        system_prompt=system_prompt,
        tools=tools,
        hooks=[SpecialistMemoryHooks(memory_client, memory_id, actor_id)],
    )
