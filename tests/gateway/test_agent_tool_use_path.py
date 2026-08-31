"""End-to-end regression tests for the *agent tool-use path*.

These tests lock down the contract that an agent's configured, authorized
tools are (a) actually supplied to the LLM provider in the provider's native
function-calling format, and (b) invoked/round-tripped correctly when the
model emits a tool call — for the streaming endpoint *and* the buffered
(non-streaming) path.

Unlike the pre-existing gateway tests, these assert on the concrete provider
*request payload* (``FakeProvider.calls[...]["tools"]``). The scriptable
``FakeProvider`` emits tool calls regardless of whether tools were sent, so
only inspecting the request payload can prove the tools were exposed to the
model — i.e. catch the "the model cannot see the enabled tools" regression.

The deterministic "fake tool" is the library ``calculate`` tool: it runs in a
pure sandbox with no I/O, so ``calculate("2 + 2") -> {"result": 4}`` is fully
deterministic and flows through the real governed ``ToolExecutor``.
"""

from __future__ import annotations

import json

import pytest

from tests.gateway.conftest import FakeProvider, make_tool_call
from tests.gateway.test_chat_runtime import (
    ALICE,
    ORG,
    build_runtime,
    create_agent,
    create_conversation,
    enable_tool,
    parse_frames,
)


def _tool_names_in_request(provider: FakeProvider, call_index: int = 0) -> set[str]:
    """Names of tools included in the LLM request for provider call *n*."""
    tools = provider.calls[call_index].get("tools") or []
    return {spec["function"]["name"] for spec in tools}


async def _run_stream(runtime, conversation_grn: str) -> list[tuple[str, dict]]:
    return parse_frames(
        [
            frame
            async for frame in runtime.stream_turn(
                org_id=ORG,
                principal_id=ALICE,
                conversation_grn=conversation_grn,
                content="What is 2 + 2?",
                model_override="fake-model",
            )
        ]
    )


# ---------------------------------------------------------------------------
# 1. Enabled + authorized tool IS included in the provider request.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_enabled_authorized_tool_is_included_in_provider_request(session_factory):
    provider = FakeProvider(script=[{"text": "The answer is 4."}])
    runtime = build_runtime(session_factory, provider)
    await enable_tool(session_factory, "calculate")
    agent_grn = await create_agent(session_factory, allowed_tools=["calculate"])
    conversation_grn = await create_conversation(session_factory, agent_grn=agent_grn)

    await _run_stream(runtime, conversation_grn)

    names = _tool_names_in_request(provider, 0)
    assert "calculate" in names

    # The tool is supplied in the provider's native function-calling format,
    # NOT smuggled into the system prompt.
    spec = provider.calls[0]["tools"][0]
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "calculate"
    assert "parameters" in spec["function"]
    system_msg = provider.calls[0]["messages"][0]
    assert system_msg.role == "system"
    assert "calculate" not in system_msg.content


# ---------------------------------------------------------------------------
# 2. A disabled tool is NOT included in the provider request.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_disabled_tool_is_excluded_from_provider_request(session_factory):
    provider = FakeProvider(script=[{"text": "ok"}])
    runtime = build_runtime(session_factory, provider)
    await enable_tool(session_factory, "calculate")
    await enable_tool(session_factory, "get_time")
    # Both org-enabled; the agent explicitly disables get_time (deny wins).
    agent_grn = await create_agent(
        session_factory,
        allowed_tools=["calculate", "get_time"],
        disabled_tools=["get_time"],
    )
    conversation_grn = await create_conversation(session_factory, agent_grn=agent_grn)

    await _run_stream(runtime, conversation_grn)

    names = _tool_names_in_request(provider, 0)
    assert "calculate" in names
    assert "get_time" not in names


@pytest.mark.asyncio
async def test_org_disabled_tool_resource_is_excluded_from_provider_request(
    session_factory,
):
    provider = FakeProvider(script=[{"text": "ok"}])
    runtime = build_runtime(session_factory, provider)
    await enable_tool(session_factory, "calculate")
    # get_time is *not* enabled as a Tool resource for the org, so even though
    # the agent declares it, it must never reach the model (opt-in governance).
    agent_grn = await create_agent(
        session_factory, allowed_tools=["calculate", "get_time"]
    )
    conversation_grn = await create_conversation(session_factory, agent_grn=agent_grn)

    await _run_stream(runtime, conversation_grn)

    names = _tool_names_in_request(provider, 0)
    assert names == {"calculate"}


# ---------------------------------------------------------------------------
# 3-5. Tool call executed, result returned to the model, final response only
#      after the tool-result round trip.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_call_executes_round_trips_and_final_answer_follows(session_factory):
    provider = FakeProvider(
        script=[
            # Turn 1: model requests the tool (no user-visible text yet).
            {
                "text": "",
                "tool_calls": [make_tool_call("calculate", expression="2 + 2")],
            },
            # Turn 2: model produces the final answer using the tool result.
            {"text": "It is 4."},
        ]
    )
    runtime = build_runtime(session_factory, provider)
    await enable_tool(session_factory, "calculate")
    agent_grn = await create_agent(session_factory, allowed_tools=["calculate"])
    conversation_grn = await create_conversation(session_factory, agent_grn=agent_grn)

    frames = await _run_stream(runtime, conversation_grn)
    events = [e for e, _ in frames]

    # (3) The model's tool call was executed and reported.
    tool_result = next(d for e, d in frames if e == "tool_result")
    assert tool_result["name"] == "calculate"
    assert tool_result["success"] is True
    # Executed through the real tool layer -> deterministic result.
    assert json.loads(tool_result["content"])["result"] == 4

    # (4) The tool result was returned to the model on the *second* provider
    #     call as a tool-role message carrying the same tool_call_id.
    assert len(provider.calls) == 2
    tool_messages = [m for m in provider.calls[1]["messages"] if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call-1"
    assert json.loads(tool_messages[0].content)["result"] == 4
    # The second request still carries the tool schema so the model may
    # continue calling tools if needed.
    assert "calculate" in _tool_names_in_request(provider, 1)

    # (5) The final assistant text is produced only AFTER the round trip:
    #     tool_call -> tool_result -> (final tokens) -> done, and the final
    #     content comes from the post-round-trip turn.
    assert events.index("tool_call") < events.index("tool_result")
    assert events.index("tool_result") < events.index("done")
    final_tokens = "".join(d["delta"] for e, d in frames if e == "token")
    assert final_tokens == "It is 4."
    # No user-visible tokens were emitted before the tool round trip.
    token_positions = [i for i, (e, _) in enumerate(frames) if e == "token"]
    assert min(token_positions) > events.index("tool_result")


# ---------------------------------------------------------------------------
# 6. Streaming path emits the expected final result and does not drop tool
#    calls, and the buffered (non-streaming) path behaves identically.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_path_does_not_drop_tool_calls(session_factory):
    provider = FakeProvider(
        script=[
            {
                "text": "",
                "tool_calls": [make_tool_call("calculate", expression="2 + 2")],
            },
            {"text": "Result: 4"},
        ]
    )
    runtime = build_runtime(session_factory, provider)
    await enable_tool(session_factory, "calculate")
    agent_grn = await create_agent(session_factory, allowed_tools=["calculate"])
    conversation_grn = await create_conversation(session_factory, agent_grn=agent_grn)

    frames = await _run_stream(runtime, conversation_grn)
    events = [e for e, _ in frames]

    # Tool call surfaced (not dropped) and carries the model's arguments.
    tool_call = next(d for e, d in frames if e == "tool_call")
    assert tool_call["name"] == "calculate"
    assert tool_call["arguments"] == {"expression": "2 + 2"}

    # Stream terminates with a single well-formed done frame carrying usage.
    assert events[-1] == "done"
    done = frames[-1][1]
    assert done["finish_reason"] == "stop"
    assert done["usage"]["total_tokens"] > 0


@pytest.mark.asyncio
async def test_non_streaming_path_completes_tool_round_trip(session_factory):
    provider = FakeProvider(
        script=[
            {
                "text": "",
                "tool_calls": [make_tool_call("calculate", expression="2 + 2")],
            },
            {"text": "Buffered: 4"},
        ]
    )
    runtime = build_runtime(session_factory, provider)
    await enable_tool(session_factory, "calculate")
    agent_grn = await create_agent(session_factory, allowed_tools=["calculate"])
    conversation_grn = await create_conversation(session_factory, agent_grn=agent_grn)

    result = await runtime.complete_turn(
        org_id=ORG,
        principal_id=ALICE,
        conversation_grn=conversation_grn,
        content="What is 2 + 2?",
        model_override="fake-model",
    )

    # The tool schema reached the model, the tool ran, and the buffered final
    # answer reflects the post-round-trip turn.
    assert "calculate" in _tool_names_in_request(provider, 0)
    assert len(provider.calls) == 2
    assert result["content"] == "Buffered: 4"
