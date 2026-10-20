"""Verdict filtering must not alter normal replies, plans or tool routing."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.history import _to_view
from app.agents.nodes.conversation import ConversationNodes
from app.llm.text import is_evaluation_reply
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

pytestmark = pytest.mark.smoke
VERDICT = '{"valid": false, "feedback": "Internal evaluation feedback"}'


@pytest.mark.parametrize("content", [VERDICT, f"```json\n{VERDICT}\n```", [{"type": "text", "text": VERDICT}]])
def test_verdict_formats(content):
    assert is_evaluation_reply(content)
    assert _to_view(AIMessage(content=content), datetime.now(timezone.utc), 1) is None
    assert _to_view(HumanMessage(content=content), datetime.now(timezone.utc), 1).content


@pytest.mark.parametrize("content", [
    "Your plan is valid.", '{"plan": [], "valid": false, "feedback": "notes"}',
    '{"valid": "false", "feedback": "notes"}', "| Year | Session | Subject Code |",
    'Explanation: ' + VERDICT,
])
def test_normal_content_is_preserved(content):
    assert not is_evaluation_reply(content)
    assert _to_view(AIMessage(content=content), datetime.now(timezone.utc), 1).content == content


def setup_node(responses):
    model = MagicMock()
    model.ainvoke = AsyncMock(side_effect=responses)
    registry = MagicMock()
    registry.get.return_value = model
    node = ConversationNodes(registry, {})
    state = {"meta": {}, "meta_confirmed": False, "raw_sols": "no enrolment yet",
             "messages": [HumanMessage(content="Hello")], "planning_requested": False}
    return node, model, state


async def test_normal_reply_uses_one_call_and_changes_only_messages():
    answer = AIMessage(content="Hello! What would you like help with?")
    node, model, state = setup_node([answer])
    result = await node.agent(state)
    assert result["messages"] == [answer]
    assert model.ainvoke.await_count == 1


async def test_legacy_verdict_removed_but_tool_exchange_retained():
    node, model, state = setup_node([AIMessage(content="Here is an explanation.")])
    call = AIMessage(content=VERDICT, tool_calls=[{"name": "lookup_subjects_tool", "args": {}, "id": "lookup"}])
    tool = ToolMessage(content="Subject facts", tool_call_id="lookup")
    old_verdict = AIMessage(content=VERDICT)
    state["messages"] = [old_verdict, call, tool, *state["messages"]]
    await node.agent(state)
    sent = model.ainvoke.call_args.args[0]
    assert old_verdict not in sent
    assert call in sent and tool in sent


async def test_accidental_verdict_retries_without_using_plan_validator():
    answer = AIMessage(content="Your existing plan remains the same.")
    node, model, state = setup_node([AIMessage(content=VERDICT), answer])
    state.update(plan="Existing free-form plan", conversation_mode="post_plan")
    result = await node.agent(state)
    assert result["messages"] == [answer]
    assert state["plan"] == "Existing free-form plan"
    assert model.ainvoke.await_count == 2


async def test_repeated_verdict_has_bounded_retry_and_safe_reply():
    node, model, state = setup_node([AIMessage(content=VERDICT), AIMessage(content=VERDICT)])
    result = await node.agent(state)
    assert not is_evaluation_reply(result["messages"][0].content)
    assert model.ainvoke.await_count == 2


@pytest.mark.parametrize("retry", [False, True])
async def test_tool_calls_preserve_routing_even_with_verdict_content(retry):
    call = AIMessage(content=VERDICT, tool_calls=[{"name": "request_plan_change_tool", "args": {}, "id": "change"}])
    responses = [AIMessage(content=VERDICT), call] if retry else [call]
    node, model, state = setup_node(responses)
    result = await node.agent(state)
    assert result["messages"][0] is call
    assert node.route_after_agent({**state, **result}) == "tools"
    assert _to_view(call, datetime.now(timezone.utc), 1) is None
    assert model.ainvoke.await_count == (2 if retry else 1)
