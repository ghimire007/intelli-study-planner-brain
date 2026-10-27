"""The plan panel and PDF exporter require subject rows, not conversational prose."""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agents.nodes.stage2 import Stage2Nodes
from app.services.study_plan_output import normalize_study_plan_output, read_study_plan
from langchain_core.messages import AIMessage

pytestmark = pytest.mark.smoke

PAYLOAD = {"plan": [
    {"year": "2024", "sessions": [{"session": "Autumn", "subjects": [
        {"code": "CSIT110", "name": "Fundamental Programming with Python", "cp": 6, "notes": "Completed"},
    ]}]},
    {"year": "2026", "sessions": [{"session": "Spring", "subjects": [
        {"code": "CSIT321", "name": "Project", "cp": 6, "notes": "Enrolled"},
    ]}]},
]}


@pytest.mark.parametrize("text", [
    json.dumps(PAYLOAD),
    "Your suggested plan:\n```json\n" + json.dumps(PAYLOAD) + "\n```",
    "Your suggested plan:\n```JSON\n" + json.dumps(PAYLOAD) + "\n```\nSome trailing prose.",
])
def test_valid_plan_always_has_a_table_and_final_json_for_the_frontend(text):
    output = normalize_study_plan_output(text)
    parsed, block = read_study_plan(output)
    assert parsed.model_dump() == PAYLOAD
    assert "| Year | Session | Subject Code | Subject Name | CP | Notes |" in output
    assert "| 2024 | Autumn | CSIT110 |" in output
    assert "| 2026 | Spring | CSIT321 |" in output
    assert output.endswith(block)
    assert normalize_study_plan_output(output) == output


@pytest.mark.parametrize("text", [
    "Here is your study plan: Autumn 2026: CSCI321 (Project).",
    '{"plan": []}',
    '{"plan": [{"year": "2026", "sessions": []}]}',
    '{"plan": [{"year": "2026", "sessions": [{"session": "Autumn", "subjects": []}]}]}',
    '{"plan": [{"year": "2026", "sessions": [{"session": "Autumn", "subjects": [{"code": "CSIT321"}]}]}]}',
])
async def test_prose_and_empty_or_incomplete_payloads_cannot_pass_as_a_plan(text):
    with pytest.raises(ValueError):
        normalize_study_plan_output(text)
    registry = MagicMock()
    node = Stage2Nodes(registry, [], no_tools_llms=registry)
    verdict = await node.evaluate({"plan": text})
    assert verdict["plan_feedback"]
    assert verdict["stage2_retry_count"] == 1
    registry.get.assert_not_called()
    output = await node.format_output({"plan": text})
    assert output["plan"] is None
    assert output["conversation_mode"] != "post_plan"
    assert "passed the evaluation" not in output["messages"][0].content


async def test_evaluator_and_final_reply_share_the_normalized_payload():
    registry = MagicMock()
    registry.get.return_value.ainvoke = AsyncMock(return_value=AIMessage(
        content='{"valid": true, "feedback": ""}',
    ))
    node = Stage2Nodes(registry, [], no_tools_llms=registry)
    verdict = await node.evaluate({"plan": json.dumps(PAYLOAD)})
    assert verdict["plan_feedback"] is None
    output = await node.format_output(verdict)
    assert output["plan"] == output["messages"][0].content
    assert read_study_plan(output["plan"])[0].model_dump() == PAYLOAD
