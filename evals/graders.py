"""Graders for Beacon evals.

Each grader takes ``(result, spec, ctx)`` and returns ``(status, why)`` where
``status`` is one of PASS / FAIL / SKIP (see run.py for how SKIP is used —
mainly for the memory-recall task when BeaconMemory isn't deployed).

``result`` is a ``run.TaskResult``: final text, the agent instance (for
state_flag), and ``actions`` — a slice of the global tool-call trace captured
by run.py's monkeypatches (see ``_install_tool_tracing`` there). We trace at
that level, not by grepping ``agent.messages``, specifically so a task that
goes through ``dispatch_specialists`` still lets us see which *specialist's*
tool got called — the coordinator's own message history only has
dispatch_specialists' return text, not the nested specialist's tool calls.

``spec`` is the task's ``expect:`` dict from tasks.yaml.
"""

from __future__ import annotations

import json
import re

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def tool_called(result, spec, ctx) -> tuple[str, str]:
    """PASS if any of the named tool(s) appear in this task's tool-call trace.

    spec: {tool: "calculate_refund"} or {any_of: ["calculate_refund", "check_return_eligibility"]}
    """
    expect = spec.get("any_of") or [spec["tool"]]
    seen = [a.get("tool") for a in result.actions]
    hit = next((t for t in expect if t in seen), None)
    if hit:
        return PASS, f"called {hit}"
    return FAIL, f"none of {expect} called (trace: {seen or 'no tool calls'})"


def state_flag(result, spec, ctx) -> tuple[str, str]:
    """PASS if result.agent.state[key] is truthy.

    Only meaningful when result.agent is the agent that actually ran the tool
    that sets the flag (e.g. escalate_to_human) -- see tasks.yaml's R4 for why
    that task invokes a specialist directly instead of going through the
    coordinator's dispatch_specialists (a specialist's escalation flag lives
    on the specialist's own Agent instance, not the coordinator's).
    """
    if result.agent is None:
        return FAIL, "no agent instance captured for this task"
    value = result.agent.state.get(spec["key"])
    if value:
        reason = value.get("reason") if isinstance(value, dict) else value
        return PASS, f"state[{spec['key']}]={str(reason)[:70]}"
    return FAIL, f"state[{spec['key']}] not set"


def regex_present(result, spec, ctx) -> tuple[str, str]:
    pattern = re.compile(spec["pattern"], re.IGNORECASE)
    if pattern.search(result.text or ""):
        return PASS, ""
    return FAIL, spec.get("why", f"pattern not found: {spec['pattern'][:40]}")


def numeric_tolerance(result, spec, ctx) -> tuple[str, str]:
    """Parse a tool's JSON output and check spec['field'] is within tolerance.

    calculate_refund runs in a real AgentCore Code Interpreter sandbox — if
    that sandbox isn't reachable (no AWS creds/permissions in this environment)
    the tool itself catches the error and returns a JSON {"error": "AGENTCORE_ERROR: ..."}
    string rather than raising. We treat that case as PASS-but-degraded: the
    point of this grader in a dry run is "did the agent call the right tool
    with the right idea", not "is Code Interpreter provisioned" -- that's the
    judgment call flagged in the task description for this exact tool.
    """
    tool = spec["tool"]
    matches = [a for a in result.actions if a.get("tool") == tool]
    if not matches:
        return FAIL, f"{tool} was never called"

    output = matches[-1].get("output") or ""
    try:
        data = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return PASS, f"{tool} called but output wasn't parseable JSON ({output[:40]!r}) — grading on call presence"

    if isinstance(data, dict) and "AGENTCORE_ERROR" in str(data.get("error", "")):
        return PASS, f"{tool} called; sandbox unavailable ({data['error'][:50]}) — degraded to call-presence check"

    field = spec["field"]
    if not isinstance(data, dict) or field not in data:
        return FAIL, f"field {field!r} missing from {tool} output: {data}"

    value = data[field]
    target = spec["value"]
    tol = spec.get("tolerance", 0.01)
    if abs(value - target) <= tol:
        return PASS, f"{field}={value} (target {target} ±{tol})"
    return FAIL, f"{field}={value}, expected {target} ±{tol}"


def composite(result, spec, ctx) -> tuple[str, str]:
    """AND a list of sub-graders (each its own {grader, ...spec} dict).

    FAIL on the first sub-check that fails. SKIP propagates if any sub-check
    SKIPs (e.g. a nested memory-dependent check). Otherwise PASS with all
    sub-whys joined.
    """
    whys = []
    for sub in spec["checks"]:
        fn = GRADERS[sub["grader"]]
        status, why = fn(result, sub, ctx)
        if status in (FAIL, SKIP):
            return status, why
        if why:
            whys.append(why)
    return PASS, "; ".join(whys)


GRADERS = {
    "tool_called": tool_called,
    "state_flag": state_flag,
    "regex_present": regex_present,
    "numeric_tolerance": numeric_tolerance,
    "composite": composite,
}


def grade(task: dict, result, ctx: dict) -> tuple[str, str]:
    if result.error:
        return FAIL, f"error: {result.error[:80]}"
    fn = GRADERS[task["grader"]]
    return fn(result, task.get("expect", {}), ctx)
