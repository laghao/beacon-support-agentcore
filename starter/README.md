# Beacon workshop — starter

Same tree as [`../app/beacon`](../app/beacon), with eight functions stubbed as `TODO`s — one exercise per
capability this repo demonstrates. Everything else (agents, tools, gateway wiring, skills) is already wired up
around these eight gaps, so you're implementing the AgentCore-specific mechanics, not plumbing.

```bash
cd starter
uv sync
agentcore dev   # from the repo root's agentcore/ config still applies — see the root README
```

## Exercises

| # | File · function | What it teaches |
| --- | --- | --- |
| 1 | `app/beacon/memory/session.py` · `get_memory_session_manager` | Wiring all four BeaconMemory strategies (semantic, preference, episodic, summarization) into per-turn retrieval |
| 2 | `app/beacon/hooks/branch_hook.py` · `SpecialistBranch.record` | Forking and appending to an AgentCore Memory branch |
| 3 | `app/beacon/hooks/memory_hook.py` · `recall` | Explicit semantic + preference recall for agents outside the main session manager |
| 4 | `app/beacon/hooks/summary_hook.py` · `build_handoff_summary` | Composing a human handoff note from a summary strategy + raw branch events |
| 5 | `app/beacon/tools/refund_calculator.py` · `calculate_refund` | Running sandboxed math in AgentCore Code Interpreter |
| 6 | `app/beacon/tools/carrier_lookup.py` · `check_carrier_service_alerts` | Driving a real browser session with the AgentCore Browser tool |
| 7 | `app/beacon/agents/coordinator.py` · `dispatch_specialists` | Parallel (`asyncio.gather`) vs. sequential specialist fan-out |
| 8 | `app/beacon/tools/escalation.py` · `escalate_to_human` | Reading/writing Strands `agent.state` from inside a tool |

Each TODO comment tells you exactly which calls to make and in what order. If you get stuck, diff against the
reference implementation:

```bash
diff -u app/beacon/hooks/branch_hook.py ../app/beacon/hooks/branch_hook.py
```

## Checking your work

```bash
uv run python ../evals/run.py --compare
```

Exercises 1-4 and 7 are what make the parallel cross-domain eval task pass — until they're implemented, the
multiagent path silently behaves like the single-agent one (no branch, no concurrency), so that task is your
signal you're done. Exercises 5, 6, and 8 have their own dedicated eval tasks (refund math, carrier lookup,
escalation trigger).

See [`../solution/README.md`](../solution/README.md) if you want to jump straight to the reference implementation
instead of implementing.
