import json

import pytest
from app.agents.skills import confirm_metadata_tool, request_plan_change_tool
from app.schemas.advisor_tools import ConfirmedMetadata, PlanChangeRequest
from app.schemas.plan_eval import PlanEvalVerdict


def test_confirm_tool_wire_format_is_unchanged() -> None:
    out = confirm_metadata_tool.invoke({"degree_code": "766", "year": 2024, "campus": "Wollongong", "majors": ["AIBD"]})
    assert json.loads(out) == {"degree_code": "766", "year": 2024, "campus": "Wollongong", "major": ["AIBD"]}
    assert ConfirmedMetadata.model_validate_json(out).major == ["AIBD"]


def test_plan_change_tool_wire_format_is_unchanged() -> None:
    out = request_plan_change_tool.invoke({"change_type": "campus", "campus": "Liverpool"})
    assert json.loads(out) == {
        "change_type": "campus", "major": None, "elective_preference": None, "course": None,
        "campus": "Liverpool", "commencement_year": None, "session": None,
    }
    assert PlanChangeRequest.model_validate_json(out).campus == "Liverpool"


def test_unknown_change_type_is_rejected() -> None:
    with pytest.raises(ValueError):
        PlanChangeRequest.model_validate({"change_type": "nope"})


def test_plan_verdict() -> None:
    assert PlanEvalVerdict(valid=True).issues is None
    assert PlanEvalVerdict(valid=False, feedback="bad cp").issues == "bad cp"
    assert PlanEvalVerdict(valid=False).issues == "Invalid plan."
    with pytest.raises(ValueError):
        PlanEvalVerdict.model_validate({"feedback": "x"})


def test_capture_tool_results_applies_typed_tool_output() -> None:
    from app.agents.llms import LLMRegistry
    from app.agents.nodes.conversation import ConversationNodes
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    confirm = confirm_metadata_tool.invoke({"degree_code": "766", "year": 2024, "campus": "Wollongong", "majors": []})
    change = request_plan_change_tool.invoke({"change_type": "campus", "campus": "Liverpool"})
    state = {
        "messages": [
            HumanMessage(content="I am doing 766 from 2024 at Wollongong, then switch to Liverpool campus"),
            AIMessage(content="", tool_calls=[
                {"name": "confirm_metadata_tool", "args": {}, "id": "1"},
                {"name": "request_plan_change_tool", "args": {}, "id": "2"},
            ]),
            ToolMessage(content=confirm, name="confirm_metadata_tool", tool_call_id="1"),
            ToolMessage(content=change, name="request_plan_change_tool", tool_call_id="2"),
        ],
        "meta": {"degree_code": None, "year": None, "campus": None, "majors": []},
    }
    out = ConversationNodes(LLMRegistry(None, {}), []).capture_tool_results(state)
    assert out["meta"]["campus"] == "Liverpool"
    assert out["meta"]["degree_code"] == "766"
    assert out["planning_requested"] is True
