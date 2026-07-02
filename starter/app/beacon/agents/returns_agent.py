"""Returns specialist — return-window eligibility and the return/exchange flow.

Same isolated-branch pattern as billing_agent.py. Returns and Billing overlap
(both touch refund math) by design: it's a realistic seam in a support org,
and the coordinator's dispatch_specialists can fan out to both at once on a
single cross-domain request (see evals/tasks.yaml's parallel-sub-agent task).
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

SYSTEM_PROMPT = """You are Beacon's Returns specialist for Northwind Outfitters.

You handle: "can I return this", return-window disputes, and exchanges.
Billing owns the final refund-amount conversation once eligibility is settled,
but you can call calculate_refund yourself to tell a customer what to expect.

Tools:
- Gateway order tools (get_order_details, check_return_eligibility)
- calculate_refund — for a preview refund amount once you've confirmed eligibility.
- load_skill("refund-policy") — the return-window and restocking-fee rules.
- escalate_to_human — for a customer disputing an ineligible-return decision who won't accept "no" (see skills/escalation-policy.md).
"""


def build_returns_agent(
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
