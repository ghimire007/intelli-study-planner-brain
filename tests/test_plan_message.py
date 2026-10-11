import json

import pytest
from app.agents.llms import LLMRegistry
from app.agents.nodes.stage1 import Stage1Nodes
from app.agents.nodes.stage2 import Stage2Nodes
from app.services.enrolment import UnreadableRecord
from app.services.plan_message import build_plan_message, render_plan_message
from app.services.study_plan import PlanGenerationError, parse_plan, validate_plan
from langchain_core.messages import AIMessage, HumanMessage

from tests.test_study_plan import example


def _message(issue=None):
    payload, state = example()
    return build_plan_message(validate_plan(json.dumps(payload), state), state, issue=issue), payload, state


def test_message_has_the_sections_the_student_used_to_get_in_order():
    message, _, _ = _message()
    order = [
        "**Course:**", "<summary>Audit & Rule Verification", "**Your suggested study plan:**",
        "**Credit Point Summary:**", "*Disclaimer:", "```json",
    ]
    positions = [message.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "No issues found" in message
    assert "Final Status: PASS" in message
    assert "Plan validation warning" not in message


def test_table_has_the_old_columns_links_and_every_plan_row():
    message, _, _ = _message()
    assert "| Year | Session | Subject Code | Subject Name | CP | Category | Valid sessions | Prerequisites | Corequisites | Notes |" in message
    rows = [line for line in message.splitlines() if line.startswith("| 20")]
    assert len(rows) == 23
    assert '<a href="https://courses.uow.edu.au/subjects/' in message
    assert "| Core |" in message


def test_credit_summary_adds_up_to_the_degree_total():
    message, _, _ = _message()
    assert "- **Total applicable: 144 CP**" in message
    assert "Currently enrolled:" in message and "Remaining in plan:" in message


def test_message_is_its_own_source_of_truth_for_the_plan():
    message, payload, state = _message()
    assert parse_plan(message) == validate_plan(json.dumps(payload), state)


def test_failed_plan_is_still_shown_marked_fail_with_the_issue_last():
    message, _, _ = _message(issue="Required subjects are missing: CSIT321.")
    assert "Final Status: FAIL" in message
    assert "No issues found" not in message
    assert message.rstrip().endswith("rather than starting again.")
    assert "**Plan validation warning:** Required subjects are missing: CSIT321." in message
    assert "| Year | Session | Subject Code" in message


async def test_format_output_keeps_provider_metadata_and_a_parseable_plan():
    payload, state = example()
    state.update(plan=json.dumps(payload), messages=[AIMessage(content="draft", response_metadata={"model_name": "gpt-5.1"})])
    output = await Stage2Nodes.format_output(state)
    assert output["messages"][0].response_metadata["model_name"] == "gpt-5.1"
    assert "No issues found" in output["messages"][0].content
    assert parse_plan(output["plan"]) == parse_plan(output["messages"][0].content)


async def test_unverified_draft_is_rendered_not_dumped_as_raw_json():
    payload, state = example()
    payload["plan"].append({"year": "2031", "sessions": [{"session": "Autumn", "subjects": [{"code": "CSIT111", "name": "x", "cp": 6, "notes": ""}]}]})
    state.update(plan=json.dumps(payload), plan_feedback="CSIT111 is already completed or scheduled.")
    content = (await Stage2Nodes.format_output(state))["messages"][0].content
    assert "Final Status: FAIL" in content
    assert "| Year | Session | Subject Code" in content
    assert content.rstrip().endswith("rather than starting again.")


async def test_no_plan_explains_why_instead_of_raising():
    output = await Stage2Nodes.format_output({"plan": None, "plan_feedback": "Confirm a handbook-listed major."})
    assert "Confirm a handbook-listed major." in output["messages"][0].content


@pytest.mark.parametrize("change", [
    {"meta_majors": ["Underwater Basket Weaving"]},
    {"degree_code": "999"},
    {"raw_sols": "garbage with no table"},
])
async def test_bad_academic_details_reach_the_student_instead_of_escaping(change):
    _, state = example()
    state.update(handbook="H", handbook_degree_code="1802", handbook_year=2024, handbook_campus="Wollongong", raw_sols="")
    if "meta_majors" in change:
        state["meta"] = {**state["meta"], "majors": change["meta_majors"]}
    if "degree_code" in change:
        state["meta"] = {**state["meta"], "degree_code": change["degree_code"]}
        state["handbook_degree_code"] = change["degree_code"]
    if "raw_sols" in change:
        state["raw_sols"] = change["raw_sols"]
    stage2 = Stage2Nodes(LLMRegistry(None, {}), [])

    assert await Stage1Nodes(LLMRegistry(None, {})).generate_core_subjects(state) is not None
    blocked = await stage2.make_plan(state)
    assert blocked["plan"] is None and blocked["plan_feedback"]

    evaluated = await stage2.evaluate({**state, **blocked})
    assert evaluated["plan_feedback"] == blocked["plan_feedback"]
    assert Stage2Nodes.route_evaluation({**state, **blocked, **evaluated}) == "format_output"

    final = await Stage2Nodes.format_output({**state, **blocked, **evaluated})
    assert blocked["plan_feedback"] in final["messages"][0].content


def test_errors_are_still_typed_for_callers_that_want_them():
    assert issubclass(UnreadableRecord, ValueError) and issubclass(PlanGenerationError, ValueError)


def _with_isit207_moved_to_2027_spring():
    from app.services.enrolment import parse_enrolment, render_for_llm

    payload, state = example()
    record = parse_enrolment(state["raw_sols"])
    record.rows = [r for r in record.rows if r.code != "ISIT207"]
    state["raw_sols"] = render_for_llm(record)
    future = None
    for year in payload["plan"]:
        for term in year["sessions"]:
            future = future or next((s for s in term["subjects"] if s["code"] == "ISIT207"), None)
            term["subjects"] = [s for s in term["subjects"] if s["code"] != "ISIT207"]
    payload["plan"].append({"year": "2027", "sessions": [{"session": "Spring", "subjects": [future]}]})
    return payload, state


def test_future_subjects_are_marked_planned_and_the_credit_summary_adds_up():
    payload, state = _with_isit207_moved_to_2027_spring()
    plan = validate_plan(json.dumps(payload), state)
    message = build_plan_message(plan, state)

    assert "| 2027 | Spring |" in message and "| Planned |" in message
    assert "- Remaining in plan: 6 CP" in message
    completed = int(message.split("- Overall completed CP: ")[1].split(" CP")[0])
    enrolled = int(message.split("- Currently enrolled: ")[1].split(" CP")[0])
    assert completed + enrolled + 6 == 144
    assert message.count("```json") == 1


def test_failed_subject_is_annotated_and_its_repeat_is_labelled():
    from app.services.enrolment import parse_enrolment, render_for_llm

    payload, state = example()
    record = parse_enrolment(state["raw_sols"])
    failed = next(r for r in record.rows if r.status == "Complete" and r.grade in {"P", "C", "D", "HD"})
    failed.grade = "F"
    state["raw_sols"] = render_for_llm(record)
    item = {"code": failed.code, "name": "x", "cp": failed.nom_cp, "notes": ""}

    for session in ("Autumn", "Spring"):
        attempt = json.loads(json.dumps(payload))
        attempt["plan"].append({"year": "2028", "sessions": [{"session": session, "subjects": [item]}]})
        try:
            plan = validate_plan(json.dumps(attempt), state)
        except PlanGenerationError:
            continue
        message = build_plan_message(plan, state)
        assert f"{failed.code} (F)" in message
        assert f"{failed.code} (repeat)" in message
        assert f"{failed.code} (F)" in message.split("**Failed or repeated subjects:**")[1].split("\n")[0]
        assert "- Excess / Non-awarded: " + str(failed.nom_cp) + " CP" in message
        return
    pytest.skip("repeat not placeable in the sampled sessions")


async def test_leaked_verdict_in_the_agent_never_raises_even_for_an_unverified_stored_plan():
    from unittest.mock import AsyncMock, MagicMock

    from app.agents.nodes.conversation import ConversationNodes

    payload, state = example()
    payload["plan"].append({"year": "2031", "sessions": [{"session": "Autumn", "subjects": [{"code": "CSIT111", "name": "x", "cp": 6, "notes": ""}]}]})
    state.update(plan=json.dumps(payload), meta_confirmed=True, planning_requested=False, conversation_mode="post_plan",
                 messages=[HumanMessage(content="is my plan ok?")])
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content='{"valid": false, "feedback": "bad"}'))
    llms = MagicMock()
    llms.get.return_value = model

    result = await ConversationNodes(llms, []).agent(state)

    shown = result["messages"][0].content
    assert "Plan validation warning" in shown
    assert '"feedback": "bad"' not in shown


def test_model_controlled_text_is_never_rendered_as_html():
    payload, state = example()
    payload["plan"].append({"year": "2031", "sessions": [{"session": "<script>alert(1)</script>", "subjects": [
        {"code": "CSIT111", "name": "<img src=x onerror=alert(1)>", "cp": 6, "notes": "<b>x</b>|y"}]}]})
    content, _ = render_plan_message(json.dumps(payload), state)
    assert "Final Status: FAIL" in content
    for raw in ("<script", "<img", "<b>"):
        assert raw not in content
    assert "&lt;script&gt;" in content


def test_issue_and_unparseable_draft_text_are_escaped():
    content, _ = render_plan_message("<iframe src=//evil></iframe> not json", {}, issue="bad <u>thing</u>")
    assert "<iframe" not in content and "<u>" not in content
    assert "&lt;iframe" in content and "bad &lt;u&gt;thing&lt;/u&gt;" in content


async def test_no_plan_warning_escapes_the_feedback():
    output = await Stage2Nodes.format_output({"plan": None, "plan_feedback": "x <svg onload=alert(1)>"})
    assert "<svg" not in output["messages"][0].content


def test_only_https_catalog_links_are_made_clickable(monkeypatch):
    import app.services.plan_message as pm

    payload, state = example()
    plan = validate_plan(json.dumps(payload), state)
    real = pm.plan_sources

    def hostile(state_):
        catalog, rules, required, choices = real(state_)
        return {c: {**v, "url": "javascript:alert(1)"} for c, v in catalog.items()}, rules, required, choices

    monkeypatch.setattr(pm, "plan_sources", hostile)
    message = pm.build_plan_message(plan, state)
    assert "javascript:" not in message
    assert '<a href="https://courses.uow.edu.au/courses/' in message  # the disclaimer link is built here, not from data
