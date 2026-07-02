# Solution

The completed reference implementation is the canonical `beacon` package at the repo root: [`../app/beacon`](../app/beacon).

There's no separate solution tree to keep in sync with the starter — `starter/app/beacon` is a full copy of
`app/beacon` with eight functions stubbed out (see [`../starter/README.md`](../starter/README.md)). Diff the two
to see exactly what each exercise expects:

```bash
diff -ru starter/app/beacon app/beacon
```

## Map of the eight surfaces

| # | File · function | Capability |
| --- | --- | --- |
| 1 | `memory/session.py` · `get_memory_session_manager` | Short-term + long-term memory (semantic, preference, episodic, summary) |
| 2 | `hooks/branch_hook.py` · `SpecialistBranch.record` | Memory branching for parallel sub-agents |
| 3 | `hooks/memory_hook.py` · `recall` | Explicit semantic/preference recall outside the main session |
| 4 | `hooks/summary_hook.py` · `build_handoff_summary` | Session-summary handoff to a human agent |
| 5 | `tools/refund_calculator.py` · `calculate_refund` | Sandboxed Code Interpreter math |
| 6 | `tools/carrier_lookup.py` · `check_carrier_service_alerts` | Live Browser-tool lookup |
| 7 | `agents/coordinator.py` · `dispatch_specialists` | Parallel vs. sequential specialist fan-out |
| 8 | `tools/escalation.py` · `escalate_to_human` | Escalation via Strands `agent.state` |

Run `agentcore dev` from the repo root against `app/beacon` (the default `codeLocation` in `agentcore/agentcore.json`)
to run this version directly — no separate config needed.
