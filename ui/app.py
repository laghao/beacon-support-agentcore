"""Beacon — Northwind Outfitters Support · Streamlit chat UI.

A single-file demo front end for Beacon (see app/beacon/main.py) that supports
both ways this repo documents running the agent:

  1. Local dev server (`agentcore dev`, default port 8080) — POSTs straight to
     the dev server's HTTP entrypoint at http://localhost:<port>/invocations.
  2. Deployed AgentCore Runtime — invoked either:
       a) via boto3's `bedrock-agentcore` data-plane client
          (`invoke_agent_runtime`), for runtimes using IAM/SigV4 auth, or
       b) via a bearer token over plain HTTPS, for runtimes configured with a
          CUSTOM_JWT authorizer — Beacon's own runtime is declared with
          `authorizerType: "CUSTOM_JWT"` in agentcore/agentcore.json, so a real
          deployment of *this* project will need a bearer token here, not
          SigV4. This mirrors exactly what `agentcore invoke --bearer-token`
          does under the hood (confirmed by reading the CLI's bundled JS —
          it skips the boto3-equivalent SDK call and instead does a raw
          `Authorization: Bearer <token>` POST to
          `https://bedrock-agentcore.<region>.amazonaws.com/runtimes/<url-encoded-arn>/invocations?qualifier=DEFAULT`
          whenever a bearer token is supplied).

Wire format, verified by reading app/beacon/main.py and the installed
bedrock_agentcore SDK (bedrock_agentcore/runtime/app.py):
  - Request body is always `{"prompt": "<text>"}` (see main.py's _extract_prompt).
  - main.py's `invoke()` is an async generator, so BedrockAgentCoreApp always
    wraps its output as `text/event-stream` — regardless of Accept header —
    with each line shaped `data: <json>\\n\\n` (see App._convert_to_sse). This
    holds for the local dev server AND a real deployed runtime, since both run
    the same entrypoint. Streamed text deltas live at
    `event["event"]["contentBlockDelta"]["delta"]["text"]` (raw Bedrock Converse
    streaming shape — main.py forwards these events largely unfiltered).

Session / actor personalization:
  - `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` sets `context.session_id`
    (read directly off the header by the SDK's request-context builder).
  - `X-Amzn-Bedrock-AgentCore-Runtime-User-Id` is the header the *deployed*
    AgentCore Runtime uses to populate `context.user_id` (confirmed by reading
    the agentcore-cli's bundled JS, which sets this header whenever it calls a
    runtime). main.py maps `context.user_id` straight to `actor_id`
    (see agent_factory / memory/session.py), which is what namespaces the
    semantic/preference/episodic memories. NOTE: the pinned local
    `bedrock_agentcore` SDK version used by `agentcore dev` does not currently
    wire this header through to `context.user_id` (its RequestContext model
    only exposes `session_id`) — so locally every request lands on
    "default-user" no matter what you type into the customer-email field
    below. The field is still sent (forward-compatible, and correct once the
    SDK catches up) — but the actor-level memory-recall demo (recognizing the
    same customer across sessions) is best shown against a deployed runtime.
    A *new session* with the same customer email is still a fine local demo
    of session continuity.
  - InvokeAgentRuntime's `runtimeSessionId` must be >= 33 characters; short,
    human-typed session ids are deterministically padded for that call only
    (see `_pad_session_id`).

Run:
    uv run --with-requirements ui/requirements.txt streamlit run ui/app.py
    # or, with a plain virtualenv:
    pip install -r ui/requirements.txt && streamlit run ui/app.py

Env vars (all optional — the sidebar lets you override every one of these):
    BEACON_RUNTIME_ARN   Deployed runtime ARN (see agentcore/agentcore.json > runtimes)
    AWS_REGION           Region for the boto3 client (default: us-west-2)
    BEACON_DEV_PORT      Local dev server port (default: 8080, matches `agentcore dev -p`)
"""

from __future__ import annotations

import json
import os
import urllib.parse
import uuid
from typing import Iterator

import requests
import streamlit as st

SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
USER_ID_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-User-Id"

st.set_page_config(page_title="Beacon — Northwind Outfitters Support", page_icon="🧭", layout="wide")


# --- helpers -----------------------------------------------------------------


def _pad_session_id(session_id: str) -> str:
    """InvokeAgentRuntime requires runtimeSessionId to be >= 33 chars.

    Deterministic so the same human-typed session id always maps to the same
    padded id (needed for conversation continuity across turns).
    """
    session_id = session_id or "default-session"
    if len(session_id) >= 33:
        return session_id[:256]
    suffix = uuid.uuid5(uuid.NAMESPACE_DNS, session_id).hex
    return f"{session_id}-{suffix}"[:256]


def _iter_sse_text(lines: Iterator[str]) -> Iterator[str]:
    """Parse `data: {json}` SSE lines and yield contentBlockDelta text.

    Raises RuntimeError on the {"error", "error_type", "message"} shape main.py
    (via BedrockAgentCoreApp) emits when the agent raises mid-stream.
    """
    for line in lines:
        if not line or not line.startswith("data: "):
            continue
        raw = line[len("data: "):]
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and "error_type" in event and "error" in event:
            raise RuntimeError(f"{event['error_type']}: {event['error']}")
        text = (
            event.get("event", {})
            .get("contentBlockDelta", {})
            .get("delta", {})
            .get("text")
        )
        if text:
            yield text


def invoke_local_dev(prompt: str, port: str, session_id: str, user_id: str) -> Iterator[str]:
    """POST to the `agentcore dev` local server (its /invocations route)."""
    url = f"http://localhost:{port}/invocations"
    headers = {
        "Content-Type": "application/json",
        SESSION_HEADER: session_id,
        USER_ID_HEADER: user_id,
    }
    try:
        resp = requests.post(url, json={"prompt": prompt}, headers=headers, stream=True, timeout=120)
    except requests.exceptions.ConnectionError as e:
        raise RuntimeError(
            f"Couldn't reach {url} — is `agentcore dev -p {port}` running?"
        ) from e
    resp.raise_for_status()
    yield from _iter_sse_text(resp.iter_lines(decode_unicode=True))


def invoke_deployed_boto3(prompt: str, region: str, runtime_arn: str, session_id: str, user_id: str) -> Iterator[str]:
    """SigV4 (IAM) path — boto3's bedrock-agentcore data-plane client."""
    import boto3  # local import: only needed for this mode

    client = boto3.client("bedrock-agentcore", region_name=region)
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=_pad_session_id(session_id),
        runtimeUserId=user_id,
        payload=json.dumps({"prompt": prompt}).encode("utf-8"),
        contentType="application/json",
        accept="text/event-stream",
    )
    body = response["response"].read().decode("utf-8")
    yield from _iter_sse_text(body.splitlines())


def invoke_deployed_bearer(
    prompt: str, region: str, runtime_arn: str, bearer_token: str, session_id: str, user_id: str
) -> Iterator[str]:
    """CUSTOM_JWT path — plain HTTPS with a bearer token, bypassing SigV4.

    Beacon's runtime declares `authorizerType: "CUSTOM_JWT"` in
    agentcore/agentcore.json, so this is the path a real deployment of this
    project needs. URL shape and header names mirror `agentcore invoke
    --bearer-token` (read directly out of the CLI's bundled JS).
    """
    encoded_arn = urllib.parse.quote(runtime_arn, safe="")
    url = f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations?qualifier=DEFAULT"
    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        SESSION_HEADER: session_id,
        USER_ID_HEADER: user_id,
    }
    resp = requests.post(url, json={"prompt": prompt}, headers=headers, stream=True, timeout=120)
    resp.raise_for_status()
    yield from _iter_sse_text(resp.iter_lines(decode_unicode=True))


# --- session state -------------------------------------------------------


if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex


# --- sidebar: mode + identity ---------------------------------------------


with st.sidebar:
    st.title("🧭 Beacon")
    st.caption("Northwind Outfitters customer support agent — AWS Strands + Bedrock AgentCore")
    st.divider()

    st.subheader("Invocation target")
    mode = st.radio(
        "Where is Beacon running?",
        ["Local dev server", "Deployed Runtime"],
        label_visibility="collapsed",
    )

    if mode == "Local dev server":
        port = st.text_input("Dev server port", value=os.getenv("BEACON_DEV_PORT", "8080"))
        st.caption("Start it with `agentcore dev` (or `agentcore dev -p <port>`) in another terminal.")
        bearer_token = ""
        region = ""
        runtime_arn = ""
    else:
        region = st.text_input("AWS region", value=os.getenv("AWS_REGION", "us-west-2"))
        runtime_arn = st.text_input(
            "Runtime ARN",
            value=os.getenv("BEACON_RUNTIME_ARN", ""),
            help="From `agentcore status` after `agentcore deploy`, or agentcore/agentcore.json.",
        )
        bearer_token = st.text_input(
            "Bearer token (optional)",
            type="password",
            help=(
                "Required if the runtime's authorizerType is CUSTOM_JWT (Beacon's is, by default — "
                "see agentcore/agentcore.json). Leave blank to invoke with plain AWS credentials "
                "(SigV4) via boto3 instead."
            ),
        )
        port = ""

    st.divider()
    st.subheader("Customer identity")
    user_id = st.text_input(
        "Customer email (used as user_id / actor_id)",
        value="avery@northwind-outfitters.example.com",
        help="Beacon namespaces memory by actor_id. Reuse the same email across turns/sessions to demo recall.",
    )
    st.text_input("Session ID", key="session_id")
    if mode == "Local dev server":
        st.caption(
            "⚠️ The locally pinned bedrock_agentcore SDK doesn't wire the user-id header through to "
            "context.user_id yet, so local runs always act as \"default-user\" regardless of the email "
            "above. Use a Deployed Runtime to demo cross-session actor recall; locally you can still "
            "demo session continuity."
        )

    col1, col2 = st.columns(2)
    if col1.button("New session", use_container_width=True):
        st.session_state.session_id = uuid.uuid4().hex
        st.rerun()
    if col2.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()


# --- main chat area ---------------------------------------------------------


st.title("Beacon — Northwind Outfitters Support")
st.caption("Ask about an order, a return, a shipment, or a billing question.")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input("How can Beacon help today?")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        buffer = ""
        try:
            if mode == "Local dev server":
                stream = invoke_local_dev(prompt, port, st.session_state.session_id, user_id)
            elif bearer_token:
                stream = invoke_deployed_bearer(
                    prompt, region, runtime_arn, bearer_token, st.session_state.session_id, user_id
                )
            else:
                if not runtime_arn:
                    raise RuntimeError("Set a Runtime ARN in the sidebar (or BEACON_RUNTIME_ARN) first.")
                stream = invoke_deployed_boto3(prompt, region, runtime_arn, st.session_state.session_id, user_id)

            for delta in stream:
                buffer += delta
                placeholder.markdown(buffer + "▌")
            placeholder.markdown(buffer or "_(no response text)_")
        except Exception as e:  # noqa: BLE001 - surface any failure mode to the demo user
            buffer = f"⚠️ {e}"
            placeholder.error(buffer)

    st.session_state.messages.append({"role": "assistant", "content": buffer})
