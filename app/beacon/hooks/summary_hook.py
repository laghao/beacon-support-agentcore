"""Session-summary handoff, backed by BeaconMemory's SUMMARIZATION strategy.

AgentCore Memory's SUMMARIZATION strategy consolidates a session's events into
a running summary in the background -- useful, but asynchronous, so it may not
have caught up by the moment a customer needs to be escalated. This hook
builds the handoff note synchronously from the two sources available at that
instant: whatever consolidated summary already exists, plus the tail of the
main branch's raw events. Either source alone is enough to hand a human agent
something useful; together they're the difference between "summary might be a
turn or two stale" and "summary is empty."

tools/escalation.py sets `agent.state["escalation"]` when the coordinator
decides to hand off; EscalationSummaryHooks.register_hooks below reacts to
that on AfterInvocationEvent so the tool itself stays a one-line decision
("this needs a human") and doesn't have to know how summaries are built.
"""

import logging
from typing import Optional

from bedrock_agentcore.memory import MemoryClient
from strands.hooks import AfterInvocationEvent, HookProvider, HookRegistry

logger = logging.getLogger(__name__)


def build_handoff_summary(
    client: Optional[MemoryClient], memory_id: Optional[str], actor_id: str, session_id: str, reason: str
) -> str:
    """Compose a human-readable handoff note for the session being escalated."""
    lines = [f"ESCALATION: {reason}", ""]

    if client and memory_id:
        try:
            summaries = client.retrieve_memories(
                memory_id=memory_id,
                namespace=f"/support/{actor_id}/{session_id}/summary",
                query=reason,
                top_k=1,
            )
        except Exception:
            summaries = []
        if summaries:
            text = summaries[0].get("content", {}).get("text", "").strip()
            if text:
                lines += ["Session summary (AgentCore Memory):", text, ""]

        try:
            recent = client.list_branch_events(
                memory_id=memory_id, actor_id=actor_id, session_id=session_id, branch_name=None, max_results=10
            )
        except Exception:
            recent = []
        if recent:
            lines.append("Most recent turns on this session:")
            for event in recent[-6:]:
                for item in event.get("payload", []):
                    conv = item.get("conversational", {})
                    text = conv.get("content", {}).get("text", "").strip()
                    role = conv.get("role", "")
                    if text:
                        lines.append(f"  [{role}] {text}")

    return "\n".join(lines)


class EscalationSummaryHooks(HookProvider):
    """Builds and logs the handoff summary once the coordinator's turn ends,
    if a tool call this turn flagged `agent.state['escalation']`.
    """

    def __init__(self, client: Optional[MemoryClient], memory_id: Optional[str], actor_id: str, session_id: str):
        self.client = client
        self.memory_id = memory_id
        self.actor_id = actor_id
        self.session_id = session_id
        self.last_handoff: Optional[str] = None

    def register_hooks(self, registry: HookRegistry) -> None:
        registry.add_callback(AfterInvocationEvent, self._maybe_handoff)

    def _maybe_handoff(self, event: AfterInvocationEvent) -> None:
        escalation = event.agent.state.get("escalation")
        if not escalation:
            return
        self.last_handoff = build_handoff_summary(
            self.client, self.memory_id, self.actor_id, self.session_id, escalation["reason"]
        )
        logger.info("Handoff summary prepared:\n%s", self.last_handoff)
        # Clear so the next turn in this session doesn't re-fire on a stale flag.
        event.agent.state.set("escalation", None)
