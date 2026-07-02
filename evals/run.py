#!/usr/bin/env python3
"""Beacon eval harness.

    uv run --project app/beacon python evals/run.py                  multiagent=True (shipped default)
    uv run --project app/beacon python evals/run.py --single-agent   multiagent=False
    uv run --project app/beacon python evals/run.py --compare        both, side by side
    uv run --project app/beacon python evals/run.py --task R1,R4     run a subset

Requires real AWS credentials with Bedrock access — every task calls the
coordinator (or a specialist) through a real Bedrock model, there's no offline
stub. BeaconGateway and BeaconMemory are each optional: tasks tagged
``requires: [gateway]`` / ``requires: [memory]`` in tasks.yaml SKIP (not FAIL)
when GATEWAY_BEACONGATEWAY_URL / MEMORY_BEACONMEMORY_ID aren't set, same as
the app itself degrades (see mcp_client/client.py, memory/session.py).

What "better" means here, honestly — mirrors this repo's own framing, not a
sales pitch for multi-agent:

  - Every task except X1 should PASS the same way in both modes. Single-agent
    (multiagent=False) still has dispatch_specialists available as a tool —
    see agents/coordinator.py's build_coordinator docstring — it just runs
    the chosen specialists sequentially in-process with no memory-branch fork,
    instead of concurrently via asyncio.gather. So multiagent isn't "smarter"
    on any single task in this suite; don't oversell it as such.
  - X1 (the cross-domain task) is the one place --compare is expected to show
    a *difference*, and it's a timing difference, not a correctness one:
    multiagent=True runs the shipping and returns specialists concurrently;
    multiagent=False runs them one after another inside the same tool call.
    Expect X1's wall time to drop under --compare, not its PASS/FAIL.
  - When BeaconMemory is deployed, multiagent=True also leaves each
    specialist's turn on its own isolated, auditable branch (hooks/branch_hook.py);
    multiagent=False's branch stays None (see coordinator.py's _run_specialist)
    — an observability difference this harness doesn't score, but worth
    knowing about if you go looking for those branches in AgentCore Memory
    after a --compare run and only find half of them.
  - On the simple lookup (R1), single-agent should be at least as fast, since
    there's no fan-out to pay for and no reason to expect it to be worse.

Judgment calls baked into this harness (see graders.py and tasks.yaml's
per-task ``notes`` for the full reasoning):

  - Tool-call tracing happens at the strands DecoratedFunctionTool.stream /
    MCPClient.call_tool_async level (see _install_tool_tracing below), not by
    grepping agent.messages, specifically so a specialist spawned inside
    dispatch_specialists is visible to the grader even though the
    coordinator's own message history only shows dispatch_specialists'
    joined return text.
  - R4 (escalation) invokes the Billing specialist directly, bypassing
    dispatch_specialists, for two reasons: a dispatched specialist's
    agent.state is on its own Agent instance, not the coordinator's; and the
    coordinator's own EscalationSummaryHooks clears agent.state["escalation"]
    back to None in its AfterInvocationEvent handler before this harness ever
    gets to look at it. See tasks.yaml's R4 notes.
  - R2's refund math (calculate_refund, via AgentCore Code Interpreter) and R3's
    carrier lookup (check_carrier_service_alerts, via the Browser tool) both
    grade primarily on tool-call presence, not on tool-output correctness —
    those sandboxes need real AWS permissions this dev environment may not
    have, and both tools already swallow their own AWS failures into an
    AGENTCORE_ERROR string rather than raising, so "was it called" is the
    stable signal either way.
  - R5 (memory recall) grades on a direct MemoryClient.retrieve_memories()
    call against the seeded preference, not on the LLM's prose — much less
    flaky than eyeballing "does this response sound concise".
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APP_DIR = REPO / "app" / "beacon"
sys.path.insert(0, str(APP_DIR))

import yaml  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.table import Table  # noqa: E402

from graders import GRADERS, PASS, FAIL, SKIP, grade  # noqa: E402

console = Console()
TASKS = yaml.safe_load((Path(__file__).parent / "tasks.yaml").read_text())["tasks"]


# --- tool-call tracing --------------------------------------------------------
# A global, in-process trace of every tool call made by *any* agent built by
# this harness (coordinator or specialist), regardless of asyncio.gather
# fan-out. Two monkeypatches, both applied once, at the class level so they
# catch every instance:
#   - DecoratedFunctionTool.stream: every @tool-decorated function (calculate_refund,
#     escalate_to_human, check_carrier_service_alerts, check_warehouse_stock, load_skill,
#     dispatch_specialists itself).
#   - MCPClient.call_tool_async: every Gateway-derived tool (get_order_status,
#     check_return_eligibility, list_customer_orders, ...), if Gateway is deployed.
ACTION_LOG: list[dict] = []
_traced = False


def _install_tool_tracing() -> None:
    global _traced
    if _traced:
        return
    _traced = True

    import strands.tools.decorator as decorator_mod

    _orig_stream = decorator_mod.DecoratedFunctionTool.stream

    async def _traced_stream(self, tool_use, invocation_state, **kwargs):
        entry = {"tool": self.tool_name, "input": dict(tool_use.get("input") or {}), "output": None}
        ACTION_LOG.append(entry)
        async for event in _orig_stream(self, tool_use, invocation_state, **kwargs):
            tool_result = getattr(event, "tool_result", None)
            if tool_result is not None:
                texts = [c.get("text") for c in tool_result.get("content", []) if isinstance(c, dict) and "text" in c]
                entry["output"] = "\n".join(t for t in texts if t)
            yield event

    decorator_mod.DecoratedFunctionTool.stream = _traced_stream

    try:
        from strands.tools.mcp.mcp_client import MCPClient
    except ImportError:
        return

    _orig_call_tool_async = MCPClient.call_tool_async

    async def _traced_call_tool_async(self, *args, **kw):
        entry = {"tool": kw.get("name"), "input": kw.get("arguments"), "output": None}
        ACTION_LOG.append(entry)
        result = await _orig_call_tool_async(self, *args, **kw)
        try:
            texts = [c.get("text") for c in result.get("content", []) if isinstance(c, dict) and "text" in c]
            entry["output"] = "\n".join(t for t in texts if t)
        except Exception:
            pass
        return result

    MCPClient.call_tool_async = _traced_call_tool_async


_install_tool_tracing()


# --- shared harness resources (mirrors app/beacon/main.py's construction) -----
from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402
from agents.coordinator import build_coordinator  # noqa: E402
from agents.billing_agent import build_billing_agent  # noqa: E402
from agents.shipping_agent import build_shipping_agent  # noqa: E402
from agents.returns_agent import build_returns_agent  # noqa: E402
from mcp_client.client import get_beacon_gateway_mcp_client  # noqa: E402
from memory.session import MEMORY_ID, get_memory_client, get_memory_session_manager  # noqa: E402
from tools.warehouse_check import make_check_warehouse_stock_tool  # noqa: E402

# A throwaway app instance to bind @app.async_task against (see
# tools/warehouse_check.py) — main.py's real BedrockAgentCoreApp is the AgentCore
# Runtime entrypoint itself; constructing our own here avoids pulling in
# main.py's @app.entrypoint / agent_factory caching for what is otherwise a
# one-line dependency of build_shipping_agent.
_eval_app = BedrockAgentCoreApp()
check_warehouse_stock_tool = make_check_warehouse_stock_tool(_eval_app)
gateway_client = get_beacon_gateway_mcp_client()
memory_client = get_memory_client()

GATEWAY_AVAILABLE = gateway_client is not None
MEMORY_AVAILABLE = MEMORY_ID is not None


def new_coordinator(multiagent: bool, session_id: str, actor_id: str):
    return build_coordinator(
        session_id=session_id,
        actor_id=actor_id,
        memory_session_manager=get_memory_session_manager(session_id, actor_id),
        memory_client=memory_client,
        memory_id=MEMORY_ID,
        gateway_client=gateway_client,
        check_warehouse_stock_tool=check_warehouse_stock_tool,
        multiagent=multiagent,
    )


def new_specialist(domain: str, actor_id: str):
    if domain == "billing":
        return build_billing_agent(gateway_client, memory_client, MEMORY_ID, actor_id, prior_turns=[])
    if domain == "shipping":
        return build_shipping_agent(
            gateway_client, memory_client, MEMORY_ID, actor_id, prior_turns=[], check_warehouse_stock_tool=check_warehouse_stock_tool
        )
    if domain == "returns":
        return build_returns_agent(gateway_client, memory_client, MEMORY_ID, actor_id, prior_turns=[])
    raise ValueError(f"unknown domain {domain!r}")


# --- task execution ------------------------------------------------------------
@dataclass
class TaskResult:
    text: str = ""
    actions: list[dict] = field(default_factory=list)
    agent: object = None
    wall_ms: int = 0
    error: str | None = None


def _requirements_met(task: dict) -> str | None:
    """Returns None if all of task['requires'] are satisfied, else a SKIP reason."""
    for req in task.get("requires", []):
        if req == "gateway" and not GATEWAY_AVAILABLE:
            return "GATEWAY_BEACONGATEWAY_URL not set — deploy BeaconGateway to run this task"
        if req == "memory" and not MEMORY_AVAILABLE:
            return "MEMORY_BEACONMEMORY_ID not set — deploy BeaconMemory to run this task"
    return None


def run_task(task: dict, multiagent: bool) -> TaskResult:
    actor_id = task.get("actor_id", "eval-customer@northwind.test")
    session_id = f"eval-{task['id']}-{'multi' if multiagent else 'single'}-{uuid.uuid4().hex[:8]}"
    start_idx = len(ACTION_LOG)
    result = TaskResult()
    t0 = time.time()
    try:
        if task.get("mode") == "specialist":
            agent = new_specialist(task["domain"], actor_id)
        else:
            agent = new_coordinator(multiagent, session_id, actor_id)
        out = agent(task["prompt"])
        result.text = str(out)
        result.agent = agent
    except Exception as e:  # noqa: BLE001
        result.error = f"{type(e).__name__}: {e}"
    result.wall_ms = int((time.time() - t0) * 1000)
    result.actions = ACTION_LOG[start_idx:]
    return result


def run_memory_recall_task(task: dict, multiagent: bool) -> tuple[str, str, int]:
    """R5's special path: grades on a direct retrieve_memories() call, not an
    agent's trace/state. See tasks.yaml's R5 notes for why."""
    reason = _requirements_met(task)
    if reason:
        return SKIP, reason, 0

    actor_id = task["actor_id"]
    t0 = time.time()

    # Run one real coordinator turn so the row is wall-time-comparable with
    # the rest of the suite and to exercise the session-manager's automatic
    # retrieval end to end -- but this text is *not* what gates PASS/FAIL.
    coordinator_note = ""
    try:
        session_id = f"eval-{task['id']}-{'multi' if multiagent else 'single'}-{uuid.uuid4().hex[:8]}"
        agent = new_coordinator(multiagent, session_id, actor_id)
        out = agent(task["prompt"])
        coordinator_note = f"; coordinator said: {str(out)[:60]!r}"
    except Exception as e:  # noqa: BLE001
        coordinator_note = f"; coordinator turn errored: {e}"

    expect = task["expect"]
    try:
        records = memory_client.retrieve_memories(
            memory_id=MEMORY_ID,
            namespace=f"/support/{actor_id}/{expect['namespace']}",
            query=expect["query"],
            top_k=3,
        )
    except Exception as e:  # noqa: BLE001
        wall_ms = int((time.time() - t0) * 1000)
        return FAIL, f"retrieve_memories errored: {e}{coordinator_note}", wall_ms

    wall_ms = int((time.time() - t0) * 1000)
    texts = [r.get("content", {}).get("text", "") for r in records]
    if any(expect["must_contain"].lower() in t.lower() for t in texts):
        return PASS, f"found {expect['must_contain']!r} in retrieved memory{coordinator_note}", wall_ms
    return (
        FAIL,
        f"{expect['must_contain']!r} not in {len(records)} retrieved record(s) — "
        f"seed may not have run yet, or extraction hasn't consolidated{coordinator_note}",
        wall_ms,
    )


def run_one(task: dict, multiagent: bool) -> tuple[str, str, int]:
    if task.get("special") == "memory_recall":
        return run_memory_recall_task(task, multiagent)

    reason = _requirements_met(task)
    if reason:
        return SKIP, reason, 0

    result = run_task(task, multiagent)
    status, why = grade(task, result, ctx={})
    return status, why, result.wall_ms


def run_suite(multiagent: bool, tasks: list[dict]) -> list[dict]:
    label = "MULTI " if multiagent else "SINGLE"
    rows = []
    for task in tasks:
        console.print(f"  [{label}] {task['id']:<3} {task['name']} …", end=" ")
        status, why, wall_ms = run_one(task, multiagent)
        color = {"PASS": "green", "FAIL": "red", "SKIP": "yellow"}[status]
        console.print(f"[{color}]{status}[/] ({wall_ms / 1000:.1f}s)", f"[dim]{why[:70]}[/]" if why else "")
        rows.append({"id": task["id"], "name": task["name"], "status": status, "why": why, "wall_ms": wall_ms})
    return rows


# --- rendering -----------------------------------------------------------------
DOT = {PASS: "[green]PASS[/]", FAIL: "[red]FAIL[/]", SKIP: "[yellow]SKIP[/]"}


def scorecard(title: str, rows: list[dict]) -> None:
    table = Table(title=title)
    table.add_column("Task")
    table.add_column("Name")
    table.add_column("Result")
    table.add_column("Time", justify="right")
    table.add_column("Why", overflow="fold")
    for r in rows:
        table.add_row(r["id"], r["name"], DOT[r["status"]], f"{r['wall_ms'] / 1000:.1f}s", r["why"])
    passed = sum(1 for r in rows if r["status"] == PASS)
    scored = sum(1 for r in rows if r["status"] != SKIP)
    total_time = sum(r["wall_ms"] for r in rows) / 1000
    table.add_row("", "TOTAL", f"{passed}/{scored} (excl. skips)", f"{total_time:.1f}s", "")
    console.print(table)


def compare_table(single: list[dict], multi: list[dict]) -> None:
    by_id = {r["id"]: r for r in multi}
    table = Table(title="Beacon evals — single-agent vs multi-agent")
    table.add_column("Task")
    table.add_column("Name")
    table.add_column("Single")
    table.add_column("Multi")
    table.add_column("Time (single → multi)")
    table.add_column("Note")
    for s in single:
        m = by_id[s["id"]]
        delta = ""
        if s["status"] != SKIP and m["status"] != SKIP:
            dt = (m["wall_ms"] - s["wall_ms"]) / 1000
            arrow = "faster" if dt < 0 else ("slower" if dt > 0 else "=")
            delta = f"{s['wall_ms'] / 1000:.1f}s → {m['wall_ms'] / 1000:.1f}s ({arrow})"
        note = ""
        if s["id"] == "X1":
            note = "expect multi faster here (concurrent fan-out); PASS/FAIL should match, see run.py docstring"
        elif s["id"] == "R4":
            note = "agent-invariant by design (bypasses dispatch_specialists)"
        table.add_row(s["id"], s["name"], DOT[s["status"]], DOT[m["status"]], delta, note)
    console.print(table)

    sp = sum(1 for r in single if r["status"] == PASS)
    ss = sum(1 for r in single if r["status"] != SKIP)
    mp = sum(1 for r in multi if r["status"] == PASS)
    ms = sum(1 for r in multi if r["status"] != SKIP)
    console.print(f"\n  single-agent: {sp}/{ss} passed   multi-agent: {mp}/{ms} passed\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Beacon eval harness")
    ap.add_argument("--single-agent", action="store_true", help="Run once with multiagent=False")
    ap.add_argument("--compare", action="store_true", help="Run both single- and multi-agent, side by side")
    ap.add_argument("--task", help="Comma-separated task IDs to run (default: all)")
    args = ap.parse_args()

    tasks = TASKS
    if args.task:
        ids = set(args.task.split(","))
        tasks = [t for t in tasks if t["id"] in ids]
        if not tasks:
            console.print(f"[red]No tasks match --task {args.task!r}[/]")
            return

    if not GATEWAY_AVAILABLE:
        console.print("[yellow]note:[/] GATEWAY_BEACONGATEWAY_URL not set — gateway-only tasks will SKIP")
    if not MEMORY_AVAILABLE:
        console.print("[yellow]note:[/] MEMORY_BEACONMEMORY_ID not set — memory-only tasks will SKIP")

    if args.compare:
        single = run_suite(multiagent=False, tasks=tasks)
        multi = run_suite(multiagent=True, tasks=tasks)
        compare_table(single, multi)
    else:
        multiagent = not args.single_agent
        rows = run_suite(multiagent=multiagent, tasks=tasks)
        scorecard(f"Beacon evals ({'multi-agent' if multiagent else 'single-agent'})", rows)


if __name__ == "__main__":
    main()
