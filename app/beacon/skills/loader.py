"""Methodology as on-demand markdown, not baked into the system prompt.

Same lever stockpilot-bedrock's decomposed agent uses: keep the coordinator's
system prompt short (a one-line index of what each skill covers) and let it
call `load_skill(name)` when a task actually matches one. Every load is then
an explicit, auditable tool call in the trace instead of thousands of tokens
of policy text on every single turn regardless of relevance.
"""

from pathlib import Path

from strands import tool

_SKILLS_DIR = Path(__file__).parent

SKILL_INDEX: dict[str, str] = {
    "refund-policy": "Return window, restocking fee rules, and how to answer a refund question.",
    "escalation-policy": "When a session must go to a human agent, and how to phrase the handoff.",
    "tone-guide": "How to phrase a response given a customer's remembered communication preference.",
    "known-issues-triage": "How to check a tracking-stall complaint against known carrier outages before assuming a lost package.",
}


def list_skills() -> str:
    """One-line index of every skill, for the coordinator's system prompt."""
    return "\n".join(f"- {name}: {desc}" for name, desc in SKILL_INDEX.items())


@tool
def load_skill(name: str) -> str:
    """Load a methodology skill's full text by name.

    Args:
        name: One of: refund-policy, escalation-policy, tone-guide, known-issues-triage.
    """
    if name not in SKILL_INDEX:
        return f"Unknown skill '{name}'. Available: {', '.join(SKILL_INDEX)}"
    path = _SKILLS_DIR / f"{name}.md"
    if not path.exists():
        return f"AGENTCORE_ERROR: skill file missing for '{name}'"
    return path.read_text()
