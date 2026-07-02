"""Billing specialist — refund eligibility, refund math, and account charges.

Runs on its own AgentCore Memory branch (see hooks/branch_hook.py) rather than
the coordinator's main-branch session manager, so a long refund investigation
never shows up in the Shipping or Returns branches, and vice versa.
"""

from typing import Optional

from bedrock_agentcore.memory import MemoryClient
from strands import Agent
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager

from hooks.memory_hook import SpecialistMemoryHooks
from model.load import load_model
from skills.loader import load_skill
from tools.escalation import escalate_to_human
from tools.refund_calculator import calculate_refund

SYSTEM_PROMPT = """You are Beacon's Billing specialist for Northwind Outfitters.

You handle: refund amounts, restocking fees, and account-charge questions.
You do NOT handle shipping delays or return-window eligibility disputes that
haven't already been decided — Shipping and Returns own those.

Tools:
- Gateway order/refund tools (get_order_details, check_return_eligibility, list_customer_orders)
- calculate_refund — ALWAYS use this for the dollar amount. Never compute a refund by hand.
- load_skill("refund-policy") — read this before answering any refund-amount question you haven't already loaded this session.
- escalate_to_human — for anything skills/escalation-policy.md flags, most commonly a refund over $500.
"""


def build_billing_agent(
    gateway_client,
    memory_client: Optional[MemoryClient],
    memory_id: Optional[str],
    actor_id: str,
    prior_turns: list[str],
) -> Agent:
    tools = [calculate_refund, load_skill, escalate_to_human]
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
