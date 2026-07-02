import os
import uuid
from typing import Optional

from bedrock_agentcore.memory import MemoryClient
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager

MEMORY_ID = os.getenv("MEMORY_BEACONMEMORY_ID")
REGION = os.getenv("AWS_REGION", "us-west-2")


def get_memory_session_manager(session_id: Optional[str], actor_id: str) -> Optional[AgentCoreMemorySessionManager]:
    """Session manager for the coordinator's main conversation branch.

    Wires all four BeaconMemory strategies (semantic, user-preference, summarization,
    episodic) into automatic per-turn retrieval. Specialist sub-agents do NOT use this —
    see hooks/branch_hook.py, which forks isolated branches via the raw MemoryClient
    instead of going through this session manager (which always writes to "main").
    """
    if not MEMORY_ID:
        return None

    # TODO(exercise 1): Build retrieval_config and return an AgentCoreMemorySessionManager.
    #
    # BeaconMemory (agentcore/agentcore.json) has four strategies, each with its own
    # namespace template — resolve {actorId}/{sessionId} into concrete namespace strings
    # and give each one a RetrievalConfig(top_k=..., relevance_score=...):
    #   - SEMANTIC:       /support/{actorId}/semantic
    #   - USER_PREFERENCE: /support/{actorId}/preferences
    #   - EPISODIC:        /support/{actorId}/episodes/{sessionId}
    #   - SUMMARIZATION:   /support/{actorId}/{sessionId}/summary
    #
    # AgentCoreMemoryConfig rejects a None session_id — synthesize one with
    # uuid.uuid4().hex if the caller didn't provide one.
    #
    # Diff against ../../../../app/beacon/memory/session.py if you get stuck.
    raise NotImplementedError("TODO: build retrieval_config and return AgentCoreMemorySessionManager")


def get_memory_client() -> Optional[MemoryClient]:
    """Raw control/data-plane client, used where the Strands session manager's
    main-branch-only model doesn't fit: memory branching (branch_hook.py) and the
    summary handoff hook (summary_hook.py) both call AgentCore Memory directly.
    """
    if not MEMORY_ID:
        return None
    return MemoryClient(region_name=REGION)
