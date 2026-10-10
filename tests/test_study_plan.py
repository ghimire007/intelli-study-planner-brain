"""Real source-data validation and provider-neutral final rendering."""
import json
from pathlib import Path

import pytest
from app.agents.nodes.stage2 import Stage2Nodes
from app.services.enrolment import parse_enrolment, project
from app.services.study_plan import PlanGenerationError, parse_plan, render_plan, validate_plan
from app.services.subject_catalog import load_subject_catalog
from langchain_core.messages import AIMessage

pytestmark = pytest.mark.smoke


def example():
    raw = (Path(__file__).parent / "fixtures" / "sols_transfer_flat.txt").read_text()
    record = parse_enrolment(raw)
    catalog = load_subject_catalog("1802")
    grouped = {}
    for row in record.rows:
        grouped.setdefault(str(row.year), {}).setdefault(row.session, []).append({
            "code": row.code, "name": catalog[row.code]["title"], "cp": row.nom_cp, "notes": "",
        })
    payload = {"plan": [{"year": year, "sessions": [{"session": session, "subjects": subjects} for session, subjects in sessions.items()]} for year, sessions in grouped.items()]}
    state = {"meta": {"degree_code": "1802", "campus": "Wollongong", "year": 2024, "major": "Software Engineering"},
             "meta_confirmed": True, "handbook_valid": True, "raw_sols": project(raw), "context_conflicts": {}}
    return payload, state


def test_table_and_json_are_generated_from_one_validated_plan():
    payload, state = example()
    plan = validate_plan(json.dumps(payload), state)
    output = render_plan(plan)
    assert parse_plan(output) == plan
    rows = [line for line in output.splitlines() if line.startswith("| 20")]
    assert len(rows) == 23
    assert "| 2026 | Annual | CSIT321 |" in output
    assert "| Year | Session | Subject Code | Subject Name | CP | Notes |" in output
    assert sum(s.cp for y in plan.plan for t in y.sessions for s in t.subjects) == 144
    assert render_plan(validate_plan(output, state)) == output


@pytest.mark.parametrize("mutation", ["unknown", "cp", "omitted", "moved", "duplicate", "major", "unconfirmed", "handbook"])
def test_invalid_or_incomplete_draft_is_rejected(mutation):
    payload, state = example()
    row = payload["plan"][0]["sessions"][0]["subjects"][0]
    if mutation == "unknown":
        row["code"] = "FAKE999"
    elif mutation == "cp":
        row["cp"] = 6
    elif mutation == "omitted":
        payload["plan"][0]["sessions"].pop()
    elif mutation == "moved":
        payload["plan"][0]["year"] = "2027"
    elif mutation == "duplicate":
        payload["plan"][0]["sessions"][0]["subjects"].append(dict(row))
    elif mutation == "major":
        state["meta"]["major"] = "Invented Major"
    elif mutation == "unconfirmed":
        state["meta_confirmed"] = False
    elif mutation == "handbook":
        state["handbook_valid"] = False
    with pytest.raises(PlanGenerationError):
        validate_plan(json.dumps(payload), state)


def test_provider_prose_cannot_override_authoritative_names_or_notes():
    payload, state = example()
    row = payload["plan"][0]["sessions"][0]["subjects"][0]
    row.update(name="Invented title", notes="Invented prerequisite")
    result = render_plan(validate_plan(json.dumps(payload), state))
    assert "Invented" not in result


async def test_exhausted_validation_never_publishes_last_draft():
    with pytest.raises(PlanGenerationError, match="Could not generate"):
        await Stage2Nodes.format_output({"plan": "incomplete draft", "plan_feedback": "Missing required subjects"})


async def test_final_message_preserves_provider_model():
    payload, state = example()
    state.update(plan=json.dumps(payload), messages=[AIMessage(content="draft", response_metadata={"model_name": "gpt-5.1"})])
    output = await Stage2Nodes.format_output(state)
    assert output["messages"][0].response_metadata["model_name"] == "gpt-5.1"
    assert parse_plan(output["plan"]) == parse_plan(output["messages"][0].content)


def test_nested_prerequisites_require_both_or_groups():
    from app.services.study_plan import requirement_satisfied

    catalog = load_subject_catalog("1802")
    expression = "(CSIT110 or CSIT111) AND (CSIT113 or CSIT123)"
    assert not requirement_satisfied(expression, {"CSIT110"}, catalog, {})
    assert requirement_satisfied(expression, {"CSIT110", "CSIT123"}, catalog, {})
    assert not requirement_satisfied("24 credit points", {"CSIT110"}, catalog, {})
    with pytest.raises(PlanGenerationError, match="manual confirmation"):
        requirement_satisfied("Permission of Head of School", set(), catalog, {})


@pytest.mark.parametrize("session,valid", [("Spring", True), ("Autumn", False)])
def test_future_elective_is_verified_against_offerings_and_prerequisites(session, valid):
    from app.services.enrolment import render_for_llm

    payload, state = example()
    record = parse_enrolment(state["raw_sols"])
    record.rows = [r for r in record.rows if r.code != "ISIT207"]
    state["raw_sols"] = render_for_llm(record)
    future_subject = None
    for year in payload["plan"]:
        for term in year["sessions"]:
            for subject in term["subjects"]:
                if subject["code"] == "ISIT207":
                    future_subject = subject
            term["subjects"] = [s for s in term["subjects"] if s["code"] != "ISIT207"]
    payload["plan"].append({"year": "2027", "sessions": [{"session": session, "subjects": [future_subject]}]})
    if valid:
        output = validate_plan(json.dumps(payload), state)
        assert any(y.year == "2027" and s.code == "ISIT207" for y in output.plan for t in y.sessions for s in t.subjects)
    else:
        with pytest.raises(PlanGenerationError, match="not offered"):
            validate_plan(json.dumps(payload), state)


async def test_confirmed_planning_request_bypasses_conversational_drafts():
    from unittest.mock import MagicMock

    from app.agents.nodes.conversation import ConversationNodes

    _, state = example()
    state["planning_requested"] = True
    llms = MagicMock()
    result = await ConversationNodes(llms, []).agent(state)
    assert result == {}
    llms.get.assert_not_called()
    assert ConversationNodes.route_after_agent(state) == "ensure_handbook"


def test_backend_builds_immutable_history_when_provider_returns_no_future_rows():
    from app.services.study_plan import merge_record_history

    _, state = example()
    complete = validate_plan(merge_record_history('{"plan":[]}', state), state)
    assert sum(len(t.subjects) for y in complete.plan for t in y.sessions) == 23
    assert any(t.session == "Annual" and s.code == "CSIT321" and s.cp == 12 for y in complete.plan for t in y.sessions for s in t.subjects)


def test_provider_cannot_move_or_rename_recorded_subjects():
    from app.services.study_plan import merge_record_history

    payload, state = example()
    payload["plan"][0]["year"] = "2029"
    payload["plan"][0]["sessions"][0]["subjects"][0]["name"] = "Invented history"
    complete = render_plan(validate_plan(merge_record_history(json.dumps(payload), state), state))
    assert "2029" not in complete
    assert "Invented history" not in complete


async def test_core_requirements_use_sources_without_calling_provider():
    from unittest.mock import MagicMock

    from app.agents.nodes.stage1 import Stage1Nodes

    _, state = example()
    state.update(handbook="Handbook", handbook_degree_code="1802", handbook_year=2024, handbook_campus="Wollongong")
    llms = MagicMock()
    result = await Stage1Nodes(llms).generate_core_subjects(state)
    llms.get.assert_not_called()
    assert json.loads(result["remaining_subjects"])["total_cp"] == 144


async def test_fully_enrolled_degree_does_not_depend_on_provider_output():
    from unittest.mock import MagicMock

    _, state = example()
    state.update(handbook="Handbook", handbook_degree_code="1802", handbook_year=2024, handbook_campus="Wollongong")
    llms = MagicMock()
    result = await Stage2Nodes(llms, []).make_plan(state)
    llms.get.assert_not_called()
    assert result["plan"] == '{"plan":[]}'
    assert result["messages"][0].response_metadata["generation_source"] == "validated_enrolment_record"


async def test_evaluator_verdict_and_internal_drafts_do_not_leak_into_conversation():
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.nodes.conversation import ConversationNodes
    from langchain_core.messages import HumanMessage

    verdict = '{"valid": false, "feedback": "The previous response violated your Step 1 wrapper requirement."}'
    draft = AIMessage(content="Unvalidated draft", additional_kwargs={"courseo_internal": True})
    old_verdict = AIMessage(content=verdict)
    question = HumanMessage(content="Please help me create a plan")
    llms = MagicMock()
    llms.get.return_value.ainvoke = AsyncMock(return_value=AIMessage(content=verdict))
    result = await ConversationNodes(llms, []).agent({"meta": {}, "meta_confirmed": False, "messages": [draft, old_verdict, question]})
    sent = llms.get.return_value.ainvoke.call_args.args[0]
    assert draft not in sent and old_verdict not in sent and question in sent
    assert "confirm your degree code" in result["messages"][0].content
    assert '"valid"' not in result["messages"][0].content


async def test_evaluator_verdict_recovers_existing_validated_plan():
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.nodes.conversation import ConversationNodes
    from langchain_core.messages import HumanMessage

    payload, state = example()
    state.update(plan=render_plan(validate_plan(json.dumps(payload), state)), messages=[HumanMessage(content="Explain my plan")], conversation_mode="post_plan")
    llms = MagicMock()
    llms.get.return_value.ainvoke = AsyncMock(return_value=AIMessage(content='```json\n{"valid": false, "feedback": "wrapper"}\n```'))
    result = await ConversationNodes(llms, []).agent(state)
    assert parse_plan(result["messages"][0].content) == parse_plan(state["plan"])


@pytest.mark.parametrize("raw", ["", "no enrolment yet"])
async def test_student_with_no_enrolment_still_gets_a_plan_attempt(raw):
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.nodes.stage2 import Stage2Nodes
    from app.services.study_plan import merge_record_history
    from langchain_core.messages import AIMessage

    _, state = example()
    state.update(raw_sols=raw, handbook="Handbook", handbook_degree_code="1802", handbook_year=2024, handbook_campus="Wollongong")
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content='{"plan":[]}'))
    llms = MagicMock()
    llms.get.return_value = model

    out = await Stage2Nodes(llms, []).make_plan(state)

    model.ainvoke.assert_awaited_once()
    assert out["plan"] == '{"plan":[]}'
    assert merge_record_history('{"plan":[]}', state)


def test_no_enrolment_is_not_a_missing_record_error():
    _, state = example()
    state["raw_sols"] = ""
    with pytest.raises(PlanGenerationError) as excinfo:
        validate_plan('{"plan":[]}', state)
    assert "Add your complete SOLS enrolment record" not in str(excinfo.value)
