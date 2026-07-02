from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agents.coordinator import build_coordinator
from mcp_client.client import get_beacon_gateway_mcp_client
from memory.session import MEMORY_ID, get_memory_client, get_memory_session_manager
from tools.warehouse_check import make_check_warehouse_stock_tool

app = BedrockAgentCoreApp()
log = app.logger

# One warehouse-check tool bound to this app instance (see tools/warehouse_check.py —
# @app.async_task needs a concrete app to register the task against).
check_warehouse_stock_tool = make_check_warehouse_stock_tool(app)

# Gateway MCP client (order/refund Lambda target + carrier OpenAPI target).
# A single client is shared across the coordinator and every specialist; Gateway
# is the source of truth for which tools those routes expose, not this file.
gateway_client = get_beacon_gateway_mcp_client()

# Raw MemoryClient for branch forking (hooks/branch_hook.py) and the escalation
# handoff summary (hooks/summary_hook.py) — both bypass the Strands session
# manager below, which only ever writes to the "main" branch.
memory_client = get_memory_client()


def agent_factory():
    cache = {}

    def get_or_create_agent(session_id, user_id):
        actor_id = user_id
        key = f"{session_id}/{actor_id}"
        if key not in cache:
            cache[key] = build_coordinator(
                session_id=session_id,
                actor_id=actor_id,
                memory_session_manager=get_memory_session_manager(session_id, actor_id),
                memory_client=memory_client,
                memory_id=MEMORY_ID,
                gateway_client=gateway_client,
                check_warehouse_stock_tool=check_warehouse_stock_tool,
                multiagent=True,
            )
        return cache[key]

    return get_or_create_agent


get_or_create_agent = agent_factory()


def _extract_prompt(payload: dict):
    """Accept harness-style messages[], tool_results[], or plain prompt string payloads."""
    if "messages" in payload:
        return payload["messages"]
    if "tool_results" in payload:
        return [{"role": "user", "content": [{"toolResult": {
            "toolUseId": tr["toolUseId"],
            "status": tr.get("status", "success"),
            "content": tr.get("content", []),
        }} for tr in payload["tool_results"]]}]
    return payload.get("prompt", "")


@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Beacon.....")

    session_id = getattr(context, "session_id", "default-session")
    user_id = getattr(context, "user_id", "default-user")
    agent = get_or_create_agent(session_id, user_id)

    prompt = _extract_prompt(payload)

    async for event in agent.stream_async(prompt):
        if not isinstance(event, dict) or "event" not in event:
            continue
        cbs = event["event"].get("contentBlockStart")
        if cbs is not None and not cbs.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
