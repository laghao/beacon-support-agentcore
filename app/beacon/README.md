Beacon's agent package. See the repo root [README.md](../../README.md) for the full workshop — this file just orients you inside `app/beacon/`.

# Layout

`main.py` is the AgentCore Runtime entrypoint (`@app.entrypoint`). `agents/` holds the coordinator and the three
specialists (Billing, Shipping, Returns). `hooks/` holds the AgentCore Memory integration: `memory_hook.py`
(explicit semantic/preference recall for specialists), `summary_hook.py` (escalation handoff summaries), and
`branch_hook.py` (memory branching for parallel specialists). `tools/` holds the Code Interpreter, Browser, and
async-task tools. `skills/` holds the on-demand methodology markdown. `memory/session.py` wires up
AgentCore Memory. `mcp_client/client.py` connects to BeaconGateway.

## Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `MEMORY_BEACONMEMORY_ID` | No | AgentCore Memory ID, injected by CDK once `agentcore deploy` runs |
| `GATEWAY_BEACONGATEWAY_URL` | No | BeaconGateway MCP endpoint, injected by CDK once deployed |
| `AWS_REGION` | No | Defaults to `us-west-2` |

Everything degrades gracefully without these — `agentcore dev` works locally with a stubbed-down agent (no
long-term memory, no Gateway tools) before you've deployed anything.

# Developing locally

`agentcore dev` starts a local server with hot-reload. In a second terminal, `agentcore dev "<prompt>"` sends it a
prompt. See the repo root README's "Run locally" section for the full two-terminal workflow.

# Deployment

`agentcore deploy` deploys this project (Runtime + Memory + Gateway) to AWS via CDK. `agentcore invoke "<prompt>"`
invokes the deployed agent.
