"""Escalation to a human agent (row: known-issue triage / escalation policy).

Deliberately a one-line decision: flag `agent.state["escalation"]` and let
hooks/summary_hook.py's EscalationSummaryHooks build the actual handoff note
once the turn finishes. Keeping the tool this thin means the coordinator's
system prompt only has to teach the model *when* to escalate (see
skills/escalation-policy.md), not how the handoff document gets built.
"""

from strands import ToolContext, tool


@tool(context=True)
def escalate_to_human(reason: str, tool_context: ToolContext) -> str:
    """Flag this session for handoff to a human support agent.

    Call this when policy requires a human (e.g. fraud suspicion, a refund
    above your authority, legal/safety language) or when the customer is
    clearly upset and de-escalation attempts haven't worked.

    Args:
        reason: One sentence a human agent can read cold — what happened and why
            this needs them.
    """
    # TODO(exercise 8): Grab the calling agent off tool_context (dict-style access:
    # tool_context["agent"]) and set agent.state["escalation"] = {"reason": reason}
    # via agent.state.set(...). Return a short confirmation string.
    raise NotImplementedError("TODO: flag agent.state['escalation'] with the reason")
