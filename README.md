# Beacon

**A customer support agent for Northwind Outfitters — coordinator + specialists, on Strands + Bedrock AgentCore, provisioned CLI-first.**

Beacon triages order-status questions, refund math, shipping-carrier delays, and known-issue
triage for a fictional DTC outdoor-gear brand. A coordinator agent handles simple lookups itself
and fans out to Billing, Shipping, and Returns specialists — running concurrently, each on its own
AgentCore Memory branch — for anything that needs specialist reasoning or spans more than one
domain.

This is the third workshop in the series, after [atlas-deal-desk](../atlas-deal-desk) and
[stockpilot-bedrock](../stockpilot-bedrock). Both of those used the Python
`bedrock-agentcore-starter-toolkit` and hand-rolled `bin/` scripts (boto3) to provision every AWS
resource. AWS has since shipped [`@aws/agentcore-cli`](https://github.com/aws/agentcore-cli), a
full rewrite: `agentcore create` scaffolds `agentcore.json` + `aws-targets.json` + an
auto-managed `cdk/` project instead of a single YAML file, and `agentcore add <resource>`
declaratively provisions memory, gateways, gateway-targets, credentials, and identity — no more
hand-rolled boto3 provisioning for the AgentCore-native resources. Beacon is the "CLI-first"
companion piece: same production rigor as Atlas and StockPilot, but the provisioning story is
`agentcore add` + `agentcore deploy`, and `bin/` is reserved for the one thing the CLI doesn't
manage — the mock order database and its Lambda.

> A detailed architectural write-up will go up on my blog at
> [Beacon](http://oussamabenlagha.de/beacon-support-agentcore.html) — not published yet; treat
> that link as a placeholder.

## What you'll build

| # | Capability | AgentCore service | Where | Provisioned by |
| --- | --- | --- | --- | --- |
| 1 | Reason→act agent loop | Runtime (`/invocations`, `/ping`) | `app/beacon/main.py` | `agentcore create` |
| 2 | Coordinator + parallel specialists | Strands agents-as-tools | `app/beacon/agents/*.py` | code |
| 3-5 | Long-term memory: semantic, user-preference, summarization | Memory strategies | `app/beacon/memory/session.py`, `hooks/memory_hook.py` | `agentcore add memory` |
| 6 | Session-summary handoff to a human agent | Memory (SUMMARIZATION) | `app/beacon/hooks/summary_hook.py` | `agentcore add memory` |
| 7 | Memory branching for parallel sub-agents | Memory (`create_event(branch=...)`) | `app/beacon/hooks/branch_hook.py` | code, on top of BeaconMemory |
| 8 | Sandboxed refund math | Code Interpreter | `app/beacon/tools/refund_calculator.py` | IAM only (see Deploy) |
| 9 | Live carrier-delay lookup on a real website | Browser tool | `app/beacon/tools/carrier_lookup.py` | IAM only (see Deploy) |
| 10 | Order/refund backend as MCP tools | Gateway + Lambda target | `gateway/order_lambda/` | `agentcore add gateway-target --type lambda-function-arn` |
| 11 | Shipping-carrier REST API as MCP tools | Gateway + OpenAPI target | `gateway/carrier_openapi.json` | `agentcore add gateway-target --type open-api-schema` |
| 12 | Tool-set semantic search | Gateway semantic search | — | automatic once a gateway has enough tools |
| 13 | Inbound auth (verified customers only) | Identity — CUSTOM_JWT | `agentcore/agentcore.json` runtime config | hand-edited (see note below) |
| 14 | Outbound auth to the carrier API | Identity — OAuth | `gateway/carrier_openapi.json` outbound-auth | `agentcore add gateway-target --outbound-auth oauth` |
| 15 | Streaming responses | Runtime SSE | `main.py`'s `stream_async` loop | — |
| 16 | Session isolation / HealthyBusy status | Runtime sessions + `/ping` | `main.py`, `tools/warehouse_check.py` | — |
| 17 | Async long-running task | `@app.async_task` | `app/beacon/tools/warehouse_check.py` | — |
| 18 | Full tracing / dashboards | Observability (OTEL → CloudWatch) | automatic once deployed | — |

Row 13's `authorizerConfiguration` isn't a flag on `agentcore add agent` for an *existing* runtime
(only at creation time) — it's hand-edited into `agentcore/agentcore.json`, confirmed valid with
`agentcore validate`. Everything else in this table is provisioned by the CLI or is plain
application code; see "Deploy" below for the one exception (Code Interpreter/Browser IAM).

## Architecture

```
                         ┌─────────────────────────────────────────┐
                         │         COORDINATOR (Strands)             │
                         │  Gateway tools (simple lookups) ·         │
                         │  load_skill · escalate_to_human ·         │
                         │  dispatch_specialists (fan-out)           │
                         └───────┬───────────┬───────────┬──────────┘
                                 │            │           │
                     asyncio.gather — isolated Memory branch per specialist
                                 │            │           │
                    ┌────────────┘      ┌─────┘     ┌─────┘
                    ▼                   ▼           ▼
                Billing            Shipping       Returns
           (Code Interpreter)   (Browser tool,   (Code Interpreter)
                    │            async warehouse       │
                    │              check)              │
                    ▼                   ▼               ▼
           ┌─────────────────────────────────────────────────┐
           │                  BeaconGateway (MCP)               │
           │  OrderRefundLookup (Lambda)  ·  CarrierStatusApi   │
           │           (OpenAPI, outbound OAuth)                │
           └───────────────────┬─────────────────────────────┘
                                ▼
                    DynamoDB (mock order DB, bin/)
                    + real carrier tracking website (Browser)

           BeaconMemory: SEMANTIC · USER_PREFERENCE · SUMMARIZATION · EPISODIC
                                │
                                ▼
                    Runtime traces/logs ──▶ CloudWatch (Observability)
```

## Repo layout

```
agentcore/       Generated by `agentcore create` — agentcore.json, aws-targets.json, cdk/.
app/beacon/       The agent package — this is the reference (the solution).
  agents/         coordinator.py + billing/shipping/returns_agent.py
  hooks/          memory_hook.py, summary_hook.py, branch_hook.py
  tools/          refund_calculator.py (Code Interpreter), carrier_lookup.py (Browser),
                  warehouse_check.py (async task), escalation.py
  skills/         Methodology as markdown, loaded on demand via skills/loader.py
gateway/          order_lambda/ (Lambda source + tool schema) + carrier_openapi.json
seed/             Synthetic customers, orders, tickets, known-issue KB, memory priors
bin/              ONLY what `agentcore add` can't do: seed data, mock order DB + its Lambda
evals/            Task suite + grader, --compare mode (single-agent vs. multi-agent)
starter/          The workshop app: same package, eight functions stubbed as TODOs
solution/         Pointer to app/beacon + the diff recipe
ui/               Streamlit chat UI (local dev server or deployed runtime)
```

## Prerequisites

- **Node.js 20+** (for `@aws/agentcore-cli`) and **Python 3.11+** with
  [`uv`](https://docs.astral.sh/uv/).
- An **AWS account** with **Bedrock model access** for the Claude model in
  `app/beacon/model/load.py`.
- **Docker is optional** — this project uses `CodeZip` builds (Python source zipped straight to
  AgentCore Runtime), not `Container`. You'd only need Docker if you switched the Lambda's
  deployment to a container image, which `bin/deploy_order_lambda.py` doesn't.

## Setup

```bash
npm install -g @aws/agentcore-cli    # verify against your own `npm view @aws/agentcore-cli` first
export AWS_PROFILE=your-profile
export AWS_REGION=us-west-2

cp .env.example .env

cd app/beacon && uv sync && cd ../..

python bin/setup_backend.py          # creates + seeds the mock order DB (DynamoDB)
python bin/deploy_order_lambda.py    # zips + deploys the Lambda; paste the printed ARN into
                                      # agentcore/agentcore.json's OrderRefundLookup target
agentcore validate                    # confirm agentcore.json is still valid after the paste
```

BeaconMemory, BeaconGateway, and both gateway targets are already declared in
`agentcore/agentcore.json` — that's what `agentcore add memory` / `agentcore add gateway` /
`agentcore add gateway-target` wrote when this repo was built. You don't need to re-run them; they
deploy the next time you run `agentcore deploy`.

## Run locally

Two terminals:

```bash
# Terminal 1
agentcore dev --logs

# Terminal 2
agentcore dev "What's the status of order NW-10042?"
agentcore dev "What's the status of order NW-10042?" --stream
```

`agentcore invoke --dev` is not a thing in this CLI — that flag belongs to the retired
`bedrock-agentcore-starter-toolkit`. Local invocation is always `agentcore dev "<prompt>"`.

For a chat UI instead of the CLI:

```bash
uv run --with-requirements ui/requirements.txt streamlit run ui/app.py
```

It supports both the local dev server and a deployed runtime — see the sidebar toggle.

## The workshop

Build it yourself in `starter/` — eight stubbed functions, one per capability, spanning memory,
branching, tools, and the coordinator's fan-out logic.

| Exercise | File · function |
| --- | --- |
| 1 Long-term memory retrieval | `memory/session.py · get_memory_session_manager` |
| 2 Memory branching | `hooks/branch_hook.py · SpecialistBranch.record` |
| 3 Explicit semantic/preference recall | `hooks/memory_hook.py · recall` |
| 4 Escalation handoff summary | `hooks/summary_hook.py · build_handoff_summary` |
| 5 Sandboxed refund math | `tools/refund_calculator.py · calculate_refund` |
| 6 Live browser lookup | `tools/carrier_lookup.py · check_carrier_service_alerts` |
| 7 Parallel specialist fan-out | `agents/coordinator.py · dispatch_specialists` |
| 8 Escalation state flag | `tools/escalation.py · escalate_to_human` |

The [starter README](starter/README.md) walks each exercise; diff against `app/beacon` when stuck.

## Measure it: the eval harness

```bash
uv run --project app/beacon python evals/run.py --compare
```

Six tasks: order lookup, refund eligibility math, a live carrier-delay lookup, an escalation
trigger, memory recall of a seeded preference, and a cross-domain task that touches both Shipping
and Returns. Read `evals/run.py`'s module docstring before assuming "multi-agent wins" — on this
suite it wins on **wall time** for the cross-domain task (concurrent specialists vs. sequential)
and on **auditability** (each specialist's turn lands on its own AgentCore Memory branch), not on
correctness; every other task is designed to pass identically in both modes. That's the honest
scorecard, not a sales pitch for multi-agent.

## Deploy to AgentCore Runtime

```bash
agentcore deploy
agentcore invoke "What's the status of order NW-10042?"
agentcore status
agentcore logs
agentcore traces list
```

CDK auto-creates the execution role and grants what `agentcore.json`'s declared resources need —
you don't hand-author IAM policy JSON for Memory, Gateway, or the Runtime itself. The two things
CDK does **not** know to grant, because nothing in `agentcore.json` declares them as a project
resource (they use the AWS-managed default Browser/Code Interpreter, not a customer-owned one),
are:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:StartCodeInterpreterSession",
        "bedrock-agentcore:StopCodeInterpreterSession",
        "bedrock-agentcore:InvokeCodeInterpreter",
        "bedrock-agentcore:StartBrowserSession",
        "bedrock-agentcore:StopBrowserSession",
        "bedrock-agentcore:ConnectBrowserAutomationStream"
      ],
      "Resource": "*"
    }
  ]
}
```

Add that as an inline policy on the Runtime's execution role (find it via `agentcore status` or
the CloudFormation stack output) after your first `agentcore deploy`.

Row 13's CUSTOM_JWT inbound auth only takes effect on the deployed Runtime — `agentcore dev`
doesn't enforce it locally. Invoking a deployed Beacon directly (outside `agentcore invoke`, which
signs for you) needs `--bearer-token <token>` from your identity provider, not SigV4.

## Observability

Every Runtime invocation and Gateway tool call is traced via OpenTelemetry straight to CloudWatch
— no extra vendor, no separate dashboard to stand up. `agentcore logs` and `agentcore traces list`
read from the same place the AWS console does; there's nothing else to wire up.

## Teardown

```bash
agentcore remove all      # resets agentcore.json to empty
agentcore deploy          # tears down the now-empty config from AWS
python bin/teardown.py    # deletes the mock order DB (DynamoDB) + its Lambda + IAM role
```

## License

MIT. Built by [Oussama Ben Lagha](https://github.com/laghao).
