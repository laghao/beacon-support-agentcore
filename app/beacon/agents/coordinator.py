"""Coordinator — triages every request, answers simple lookups itself, and
fans out to Billing/Shipping/Returns for anything else.

The fan-out (dispatch_specialists) runs the chosen specialists concurrently
with asyncio.gather, each on its own AgentCore Memory branch (hooks/branch_hook.py)
forked off the coordinator's own main-branch conversation. That's the
"parallel sub-agents with isolated memory branches" pattern this repo adds on
top of atlas-deal-desk's parallel-subagents-as-tools design (which used Memory
but not branching).
"""

import asyncio
from typing import Optional

from bedrock_agentcore.memory import MemoryClient
from strands import Agent, tool
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager

from agents.billing_agent import build_billing_agent
from agents.returns_agent import build_returns_agent
from agents.shipping_agent import build_shipping_agent
from hooks.branch_hook import open_branch
from hooks.summary_hook import EscalationSummaryHooks
from model.load import load_model
from skills.loader import list_skills, load_skill
from tools.escalation import escalate_to_human

SYSTEM_PROMPT_TEMPLATE = """You are Beacon, the customer support coordinator for Northwind Outfitters,
a DTC outdoor-gear brand.

Handle simple, single-domain lookups yourself using the Gateway order/carrier
tools directly (e.g. "what's my order status", "when will it arrive").

For anything that needs specialist reasoning or spans more than one domain —
refund math, return-window disputes, carrier-delay triage, or a request that
touches two of those at once — call dispatch_specialists with the domain(s)
involved: billing, shipping, returns. Each runs with its own tools and its
own isolated memory branch, so calling more than one at once is normal and
they won't see each other's work-in-progress.

Call escalate_to_human yourself for anything skills/escalation-policy.md
flags, whether or not you dispatched to a specialist first.

Skills available (call load_skill(name) to read the full text):
{skills}
"""


def build_coordinator(
    session_id: str,
    actor_id: str,
    memory_session_manager,
    memory_client: Optional[MemoryClient],
    memory_id: Optional[str],
    gateway_client,
    check_warehouse_stock_tool,
    multiagent: bool = True,
) -> Agent:
    """Build the coordinator agent for one session/actor.

    multiagent=False collapses dispatch_specialists into a same-process direct
    call with no branch fork and no concurrency — this is the "single-agent"
    side of evals/run.py --compare, not a separate code path to maintain.
    """

    async def _run_specialist(domain: str, request: str) -> str:
        if multiagent and memory_client and memory_id:
            branch = open_branch(memory_client, memory_id, actor_id, session_id, branch_name=domain)
            history = branch.prior_turns()
        else:
            branch = None
            history = []

        if domain == "billing":
            agent = build_billing_agent(gateway_client, memory_client, memory_id, actor_id, history)
        elif domain == "shipping":
            agent = build_shipping_agent(
                gateway_client, memory_client, memory_id, actor_id, history, check_warehouse_stock_tool
            )
        elif domain == "returns":
            agent = build_returns_agent(gateway_client, memory_client, memory_id, actor_id, history)
        else:
            return f"Unknown domain '{domain}'"

        result = await agent.invoke_async(request)
        text = str(result)
        if branch is not None:
            branch.record(request, text)
        return text

    @tool
    async def dispatch_specialists(request: str, domains: list[str]) -> str:
        """Fan out to one or more specialists (billing, shipping, returns).

        Args:
            request: The customer request to hand to each specialist, verbatim
                or lightly reframed for their domain.
            domains: Which specialists to invoke, e.g. ["billing"] or
                ["shipping", "returns"] for a cross-domain request.
        """
        chosen = [d for d in domains if d in ("billing", "shipping", "returns")] or ["billing"]
        if multiagent:
            results = await asyncio.gather(*(_run_specialist(d, request) for d in chosen))
        else:
            results = [await _run_specialist(d, request) for d in chosen]
        return "\n\n".join(f"[{d}]\n{r}" for d, r in zip(chosen, results))

    tools = [dispatch_specialists, escalate_to_human, load_skill]
    if gateway_client:
        tools.append(gateway_client)

    escalation_hooks = EscalationSummaryHooks(memory_client, memory_id, actor_id, session_id)

    return Agent(
        model=load_model(),
        session_manager=memory_session_manager,
        conversation_manager=NullConversationManager(),
        system_prompt=SYSTEM_PROMPT_TEMPLATE.format(skills=list_skills()),
        tools=tools,
        hooks=[escalation_hooks],
    )
