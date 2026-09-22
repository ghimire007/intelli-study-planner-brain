"""Context handoff tests: mocked models/tools, no network or database required."""
import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from app.agents import graph as graph_module
from app.agents.history import _to_view
from app.agents.skills import confirm_metadata_tool
from app.api.v1.chat import _get_agent_service
from app.main import app
from app.prompts.builder import build_system_prompt
from app.schemas.chat import ChatContext, ChatRequest
from app.services import agent_chat_service as service_module
from app.services.chat_context import InvalidChatContext, SessionNotFound, intake_context
from app.services.course_catalog import COURSE_TITLES
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

pytestmark = pytest.mark.smoke

RECORD = """Student Name: Private Person (1234567)
Course: 766
Campus: Wollongong
Major: SENG
| Year | Session | Campus | Subject Code | NomCP | Mark | Grade | Status |
| 2024 | Autumn | Wollongong | CSIT110 | 6 | 88 | HD | Complete |
"""


def student(**changes):
    return SimpleNamespace(**{
        "id": uuid.uuid4(), "degree_code": "766", "commencement_year": 2024,
        "campus": "Wollongong", "major": "SENG", "elective_interests": [],
        "email": "private@example.com", "display_name": "Private Person",
        "password_hash": "secret", **changes,
    })


def prompt_for(state):
    return build_system_prompt(meta=state["meta"], meta_confirmed=state["meta_confirmed"],
                               handbook=None, raw_sols=state.get("raw_sols", ""),
                               field_sources=state["field_sources"], conflicts=state["context_conflicts"],
                               degree_name=COURSE_TITLES.get(state["meta"].get("degree_code")))


def test_authoritative_profile_and_targeted_missing_record():
    state = intake_context(student(), None, {})
    assert state["meta"] == {"degree_code": "766", "year": 2024, "campus": "Wollongong",
                             "major": "SENG", "elective_interests": []}
    assert not state["meta_confirmed"]
    prompt = prompt_for(state)
    assert '"missing_planning_fields": ["enrolment_record"]' in prompt
    assert '"degree_name": "Bachelor of Computer Science"' in prompt
    assert "degree code (e.g. 766)" in prompt
    assert '"source": "saved_profile", "confirmed": false' in prompt
    assert "private@example.com" not in prompt
    assert "Private Person" not in prompt
    assert "secret" not in prompt


def test_unknowns_and_null_hints_do_not_invent_values():
    state = intake_context(student(degree_code=None, campus=None, commencement_year=None,
                                   major=None, elective_interests=None),
                           ChatContext(profile={"degree_code": None}), {})
    assert state["meta"] == {}
    assert not state["meta_confirmed"]
    assert '"degree_name": null' in prompt_for(state)
    assert COURSE_TITLES.get("unknown") is None


def test_context_record_is_projected_and_does_not_include_pii():
    state = intake_context(student(), ChatContext(enrolment_record=RECORD), {})
    assert "CSIT110" in state["raw_sols"]
    assert "Private Person" not in json.dumps(state)
    assert "1234567" not in json.dumps(state)
    assert "88" not in state["raw_sols"]
    assert state["context_observations"]["enrolment_record"]["degree_code"] == "766"


def test_conflicting_hint_does_not_overwrite_authoritative_profile():
    state = intake_context(student(), ChatContext(profile={"degree_code": "1807"}), {})
    assert state["meta"]["degree_code"] == "766"
    assert state["context_conflicts"]["degree_code"]["incoming"] == "1807"
    assert '"conflicts_to_clarify": {"degree_code"' in prompt_for(state)


def test_corrections_survive_replayed_hints_and_record():
    user = student()
    context = ChatContext(profile={"campus": "Wollongong"}, enrolment_record=RECORD)
    state = intake_context(user, context, {})
    confirmed = {"degree_code": "766", "year": 2023, "campus": "Liverpool", "major": "SENG"}
    state.update(graph_module.fold_tool_results(state, [ToolMessage(
        content=json.dumps(confirmed), name="confirm_metadata_tool", tool_call_id="confirm",
    )]))
    assert state["meta_confirmed"]
    updated = intake_context(user, context, state)
    assert updated["meta"]["year"] == 2023
    assert updated["meta"]["campus"] == "Liverpool"
    assert not updated["context_conflicts"]
    assert updated["meta_confirmed"]
    assert updated["field_sources"]["campus"] == {"source": "conversation", "confirmed": True}
    assert intake_context(user, ChatContext(profile={"campus": None}), updated)["meta"] == updated["meta"]


def test_new_record_conflict_preserves_unrelated_confirmation():
    state = intake_context(student(), None, {})
    state.update(graph_module.fold_tool_results(state, [ToolMessage(
        content=json.dumps({"degree_code": "766", "year": 2023, "campus": "Wollongong"}),
        name="confirm_metadata_tool", tool_call_id="confirm",
    )]))
    updated = intake_context(student(), ChatContext(enrolment_record=RECORD), state)
    assert updated["meta"]["year"] == 2023
    assert updated["context_conflicts"]["year"]["incoming"] == 2024
    assert updated["field_sources"]["campus"]["confirmed"]
    assert not updated["meta_confirmed"]


def test_invalid_record_cannot_mutate_previous_state():
    state = intake_context(student(), ChatContext(enrolment_record=RECORD), {})
    before = deepcopy(state)
    with pytest.raises(InvalidChatContext, match="complete SOLS enrolment table"):
        intake_context(student(), ChatContext(enrolment_record="Student: Private Person garbage"), state)
    assert state == before
    assert intake_context(student(), None, state)["raw_sols"] == state["raw_sols"]


@pytest.mark.parametrize("context", [
    {"profile": {"user_id": str(uuid.uuid4())}}, {"profile": {"email": "x@y.com"}},
    {"profile": {"degree_code": "Bachelor of Computer Science"}},
    {"profile": {"commencement_year": "2024"}}, {"profile": {"elective_interests": [""]}},
    {"enrolment_record": {}}, {"enrolment_record": "x" * 100001},
])
def test_context_validation(context):
    with pytest.raises(ValidationError):
        ChatRequest(message="Hello", input_type="question", context=context)


def make_service(monkeypatch, prior=None):
    db = MagicMock()
    db.commit = AsyncMock()
    user = student()
    service = service_module.AgentChatService(db, user)
    config = SimpleNamespace(provider=SimpleNamespace(value="gemini"), model="selected-model", credential_id=None)
    service._resolver = SimpleNamespace(resolve=AsyncMock(return_value=config))
    service._invoke = AsyncMock()
    graph = SimpleNamespace(aget_state=AsyncMock(return_value=SimpleNamespace(values=prior or {"meta": {}})))
    monkeypatch.setattr(service_module, "build_advisor_graph", lambda *args: graph)
    monkeypatch.setattr(service_module, "get_checkpointer", lambda: None)
    monkeypatch.setattr(service_module, "latest_reply", AsyncMock(return_value="LLM reply"))
    return service


async def test_service_handoff_keeps_question_separate_and_unchanged(monkeypatch):
    service = make_service(monkeypatch)
    message = "  Create a study plan for me — please.\n"
    await service.start_session(message, input_type="question", context=ChatContext(enrolment_record=RECORD))
    payload = service._invoke.call_args.args[2]
    assert payload["messages"][0].content == message
    assert payload["meta"]["degree_code"] == "766"
    assert payload["meta"]["major"] == "SENG"
    assert "CSIT110" in payload["raw_sols"]
    assert "Private Person" not in str(payload)


async def test_followup_uses_owned_checkpoint_and_retains_context(monkeypatch):
    prior = intake_context(student(), ChatContext(enrolment_record=RECORD), {})
    service = make_service(monkeypatch, prior)
    session = SimpleNamespace(user_id=service._user.id, model="selected-model", credential_id=None)
    service._db.get = AsyncMock(return_value=session)
    await service.continue_session(uuid.uuid4(), "What next?")
    payload = service._invoke.call_args.args[2]
    assert payload["raw_sols"] == prior["raw_sols"]
    assert payload["meta"] == prior["meta"]
    assert payload["messages"][0].content == "What next?"


async def test_cross_account_denied_before_context_or_graph(monkeypatch):
    service = make_service(monkeypatch)
    service._db.get = AsyncMock(return_value=SimpleNamespace(user_id=uuid.uuid4()))
    with pytest.raises(SessionNotFound):
        await service.continue_session(uuid.uuid4(), "Hello", context=ChatContext(enrolment_record=RECORD))
    service._resolver.resolve.assert_not_awaited()
    service._invoke.assert_not_awaited()


async def test_real_graph_passes_context_to_selected_mock_llm(monkeypatch):
    model = MagicMock()
    model.bind_tools.return_value = model
    answer = "**Yes** — let's explore your options.\n\n[Handbook](https://example.com)"
    model.ainvoke = AsyncMock(return_value=AIMessage(content=answer))
    factory = MagicMock(return_value=model)
    monkeypatch.setattr(graph_module, "make_chat_model", factory)
    graph = graph_module.build_advisor_graph(MagicMock(), InMemorySaver(), "selected-config")
    state = intake_context(student(), None, {})
    state.update(messages=[HumanMessage(content="Hi!")], handbook=None)
    result = await graph.ainvoke(state, {"configurable": {"thread_id": str(uuid.uuid4())}})
    factory.assert_called_once_with("selected-config")
    messages = model.ainvoke.call_args.args[0]
    assert '"degree_code": "766"' in messages[0].content
    assert "Bachelor of Computer Science" in messages[0].content
    assert messages[-1].content == "Hi!"
    assert result["messages"][-1].content == answer


def test_utf8_markdown_and_structured_plan_are_preserved():
    plan = {"plan": [{"year": "2026", "sessions": [{"session": "Autumn", "subjects": [
        {"code": "CSIT111", "name": "Programming Fundamentals", "cp": 6, "notes": ""},
    ]}]}]}
    content = "**Study plan** — café, Y\n```json\n" + json.dumps(plan) + "\n```"
    view = _to_view(AIMessage(content=content), datetime.now(timezone.utc), 1)
    assert view.content == content
    assert "&#" not in view.content
    assert json.loads(view.content.split("```json\n")[1].split("\n```")[0]) == plan


@pytest.mark.parametrize("continue_chat", [False, True])
async def test_routes_forward_typed_context_and_report_bad_records(continue_chat):
    service = AsyncMock()
    method = service.continue_session if continue_chat else service.start_session
    method.side_effect = InvalidChatContext("Paste the complete SOLS enrolment table.")
    previous = app.dependency_overrides.copy()
    app.dependency_overrides[_get_agent_service] = lambda: service
    path = "/api/v1/chat" + (f"/{uuid.uuid4()}" if continue_chat else "")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(path, json={"message": "Hello", "input_type": "question",
                                                    "context": {"profile": {"degree_code": "766"}}})
        assert response.status_code == 422
        assert "SOLS" in response.json()["detail"]
        assert method.call_args.kwargs["context"].profile.degree_code == "766"
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_partial_confirmation_does_not_verify_other_saved_fields():
    state = intake_context(student(), None, {})
    updates = graph_module.fold_tool_results(state, [ToolMessage(
        content=confirm_metadata_tool.invoke({"major": "Software Engineering"}),
        name="confirm_metadata_tool", tool_call_id="partial",
    )])
    assert updates["meta"]["major"] == "Software Engineering"
    assert updates["meta"]["degree_code"] == "766"
    assert not updates["meta_confirmed"]


async def test_graph_confirmation_and_followup_retain_correction(monkeypatch):
    model = MagicMock()
    model.bind_tools.return_value = model
    model.ainvoke = AsyncMock(side_effect=[
        AIMessage(content="", tool_calls=[{"name": "confirm_metadata_tool", "args": {
            "degree_code": "766", "year": 2023, "campus": "Liverpool", "major": "SENG",
        }, "id": "confirm"}]),
        AIMessage(content="Model-generated acknowledgement"),
        AIMessage(content="Model-generated follow-up"),
    ])
    monkeypatch.setattr(graph_module, "make_chat_model", lambda config: model)
    graph = graph_module.build_advisor_graph(MagicMock(), InMemorySaver(), "chosen-model")
    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    context = ChatContext(profile={"campus": "Wollongong"}, enrolment_record=RECORD)
    state = intake_context(student(), context, {})
    state.update(messages=[HumanMessage(content="Actually I started in 2023 at Liverpool. The rest is correct.")], handbook=None)
    result = await graph.ainvoke(state, config)
    assert result["meta_confirmed"]
    assert result["handbook"] is None
    followup = intake_context(student(), context, result)
    followup["messages"] = [HumanMessage(content="What next?")]
    result = await graph.ainvoke(followup, config)
    assert result["meta"]["campus"] == "Liverpool"
    assert result["meta"]["year"] == 2023
    assert result["meta"]["elective_interests"] == []
    assert not result["context_conflicts"]
    assert result["messages"][-1].content == "Model-generated follow-up"
    assert len([m for m in result["messages"] if isinstance(m, HumanMessage)]) == 2


def test_catalog_mapping_matches_authoritative_scraped_metadata():
    from pathlib import Path

    for code, title in COURSE_TITLES.items():
        source = json.loads((Path(__file__).resolve().parents[1] / "seeds" / "scraped" / f"course_{code}.json").read_text())
        assert source["code"] == code
        assert source["title"] == title


async def test_invalid_followup_does_not_invoke_or_overwrite_checkpoint(monkeypatch):
    prior = intake_context(student(), ChatContext(enrolment_record=RECORD), {})
    before = deepcopy(prior)
    service = make_service(monkeypatch, prior)
    service._db.get = AsyncMock(return_value=SimpleNamespace(user_id=service._user.id))
    with pytest.raises(InvalidChatContext):
        await service.continue_session(uuid.uuid4(), "Please use this", context=ChatContext(enrolment_record="garbage"))
    service._invoke.assert_not_awaited()
    service._db.commit.assert_not_awaited()
    assert before == prior


async def test_context_cannot_bypass_authentication():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/v1/chat", json={"message": "Hi", "input_type": "question",
                                                         "context": {"profile": {"degree_code": "766"}}})
    assert response.status_code == 401


def test_failed_tool_does_not_verify_handbook_or_metadata():
    state = intake_context(student(), None, {})
    updates = graph_module.fold_tool_results(state, [ToolMessage(
        content="tool failed", name="fetch_handbook_tool", tool_call_id="fail", status="error",
    )])
    assert "handbook" not in updates
    assert "meta_confirmed" not in updates


def test_reloading_projected_record_preserves_multiple_majors():
    raw = RECORD.replace("Major: SENG", "Major: SENG\nSecond Major: AIBD")
    first = intake_context(student(), ChatContext(enrolment_record=raw), {})
    second = intake_context(student(), None, first)
    assert second["raw_sols"] == first["raw_sols"]
    assert "AIBD" in second["raw_sols"]


def test_unknown_parser_campus_remains_unknown():
    from app.services.sols_parser import _PARSER_MODEL_PROMPT, SOLSMeta

    assert SOLSMeta(degree_code=None, year=None, campus=None).campus is None
    assert 'default to "Wollongong"' not in _PARSER_MODEL_PROMPT
