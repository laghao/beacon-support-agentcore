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

    # AgentCoreMemoryConfig rejects None; OAuth/CUSTOM_JWT callers can reach us
    # without a runtime session header, so synthesize one when absent.
    session_id = session_id or uuid.uuid4().hex

    retrieval_config = {
        f"/support/{actor_id}/semantic": RetrievalConfig(top_k=3, relevance_score=0.5),
        f"/support/{actor_id}/preferences": RetrievalConfig(top_k=3, relevance_score=0.5),
        f"/support/{actor_id}/episodes/{session_id}": RetrievalConfig(top_k=5, relevance_score=0.5),
        f"/support/{actor_id}/{session_id}/summary": RetrievalConfig(top_k=3, relevance_score=0.5),
    }

    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(
            memory_id=MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config=retrieval_config,
        ),
        REGION,
    )


def get_memory_client() -> Optional[MemoryClient]:
    """Raw control/data-plane client, used where the Strands session manager's
    main-branch-only model doesn't fit: memory branching (branch_hook.py) and the
    summary handoff hook (summary_hook.py) both call AgentCore Memory directly.
    """
    if not MEMORY_ID:
        return None
    return MemoryClient(region_name=REGION)
