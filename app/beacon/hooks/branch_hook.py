"""Memory branching for parallel specialist sub-agents.

The coordinator's own conversation lives on the "main" branch of the session
(via memory/session.py's AgentCoreMemorySessionManager, which always writes to
"main"). When the coordinator fans out to Billing/Shipping/Returns, each
specialist gets its own branch forked off the current tip of main — the same
idea as a git branch: an isolated history that starts from a shared point and
can be read back without polluting the other specialists' context or the
coordinator's own turn-by-turn history.

This is why specialists can run concurrently (asyncio.gather in
agents/coordinator.py) without racing on the same conversation history, and
why re-invoking the same specialist later in the session picks up its own
prior turns instead of the coordinator's or a sibling specialist's.
"""

from dataclasses import dataclass
from typing import Optional

from bedrock_agentcore.memory import MemoryClient


@dataclass
class SpecialistBranch:
    """A specialist's isolated memory branch for one session."""

    client: MemoryClient
    memory_id: str
    actor_id: str
    session_id: str
    branch_name: str
    root_event_id: Optional[str]

    def prior_turns(self, max_results: int = 10) -> list[str]:
        """Return this branch's own prior turns, oldest first, as plain text.

        Returns [] the first time a specialist is invoked in a session — there is
        nothing to branch from yet, and that's fine (root_event_id is None until
        the first record() call, at which point the branch forks off main's tip).
        """
        events = self.client.list_branch_events(
            memory_id=self.memory_id,
            actor_id=self.actor_id,
            session_id=self.session_id,
            branch_name=self.branch_name,
            max_results=max_results,
        )
        turns = []
        for event in events:
            for item in event.get("payload", []):
                text = item.get("conversational", {}).get("content", {}).get("text")
                if text:
                    turns.append(text)
        return turns

    def record(self, user_text: str, assistant_text: str) -> None:
        """Persist one turn to this branch, forking off main's tip on first use."""
        branch = {"name": self.branch_name}
        if self.root_event_id is not None:
            branch["rootEventId"] = self.root_event_id
        event = self.client.create_event(
            memory_id=self.memory_id,
            actor_id=self.actor_id,
            session_id=self.session_id,
            branch=branch,
            messages=[(user_text, "USER"), (assistant_text, "ASSISTANT")],
        )
        # Only the very first event on a new branch needs rootEventId; later
        # calls just need the branch name to keep appending to it.
        self.root_event_id = None
        _ = event


def _tip_of_main(client: MemoryClient, memory_id: str, actor_id: str, session_id: str) -> Optional[str]:
    """The most recent main-branch event, used as the fork point for a new branch."""
    events = client.list_branch_events(
        memory_id=memory_id, actor_id=actor_id, session_id=session_id, branch_name=None, max_results=100
    )
    return events[-1]["eventId"] if events else None


def open_branch(
    client: MemoryClient, memory_id: str, actor_id: str, session_id: str, branch_name: str
) -> SpecialistBranch:
    """Open (or resume) a specialist's branch for this session.

    Safe to call every time the coordinator dispatches to a specialist: if the
    branch already has events, root_event_id is unused (record() only sends it
    on a branch's first event) and prior_turns() already returns its history.
    """
    root_event_id = _tip_of_main(client, memory_id, actor_id, session_id)
    return SpecialistBranch(
        client=client,
        memory_id=memory_id,
        actor_id=actor_id,
        session_id=session_id,
        branch_name=branch_name,
        root_event_id=root_event_id,
    )
