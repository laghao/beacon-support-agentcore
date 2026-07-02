"""Explicit semantic + user-preference recall for specialist sub-agents.

The coordinator gets long-term memory "for free": memory/session.py wires
BeaconMemory's four strategies into AgentCoreMemorySessionManager's
retrieval_config, which retrieves and injects matching records into every
turn automatically (see the SDK's retrieve_customer_context in
bedrock_agentcore.memory.integrations.strands.session_manager).

Billing/Shipping/Returns specialists deliberately do NOT use that session
manager -- they run on isolated memory branches (hooks/branch_hook.py) so
their turn-by-turn history never mixes with the coordinator's or with each
other's. That means they also don't get the automatic retrieval. This hook
gives them the same semantic-facts + preferences recall, explicitly, so a
specialist that has never seen this customer before still knows their order
history and tone preference on its very first turn.
"""

from typing import Optional

from bedrock_agentcore.memory import MemoryClient
from strands.hooks import BeforeInvocationEvent, HookProvider, HookRegistry


def recall(
    client: Optional[MemoryClient],
    memory_id: Optional[str],
    actor_id: str,
    query: str,
    top_k: int = 3,
) -> list[str]:
    """Query CustomerFacts (SEMANTIC) + CustomerPreferences (USER_PREFERENCE) directly.

    Returns [] if memory isn't configured yet (e.g. before `agentcore add memory`
    or when running evals/run.py --agent single without a MEMORY_BEACONMEMORY_ID env
    var) rather than raising -- a specialist with no memory recall is still useful,
    just less personalized.
    """
    if not client or not memory_id:
        return []

    items: list[str] = []
    for namespace in (f"/support/{actor_id}/semantic", f"/support/{actor_id}/preferences"):
        try:
            records = client.retrieve_memories(
                memory_id=memory_id, namespace=namespace, query=query, top_k=top_k
            )
        except Exception:
            continue
        for record in records:
            content = record.get("content", {})
            text = content.get("text", "").strip() if isinstance(content, dict) else ""
            if text:
                items.append(text)
    return items


class SpecialistMemoryHooks(HookProvider):
    """Attach to a specialist Agent to recall shared customer context on its first turn."""

    def __init__(self, client: Optional[MemoryClient], memory_id: Optional[str], actor_id: str):
        self.client = client
        self.memory_id = memory_id
        self.actor_id = actor_id

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(BeforeInvocationEvent, self._inject_context)

    def _inject_context(self, event: BeforeInvocationEvent) -> None:
        if not event.messages:
            return
        last = event.messages[-1]
        if last.get("role") != "user" or not last.get("content"):
            return
        query_block = next((b for b in last["content"] if "text" in b), None)
        if not query_block:
            return

        context_items = recall(self.client, self.memory_id, self.actor_id, query_block["text"])
        if context_items:
            context_text = "\n".join(context_items)
            last["content"].insert(0, {"text": f"<customer_context>{context_text}</customer_context>"})
