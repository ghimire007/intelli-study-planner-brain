import json

import pytest
from app.agents.llms import LLMRegistry
from app.agents.nodes.stage1 import Stage1Nodes
from app.schemas.core_subjects import CoreEvalVerdict, CoreSubjectFormatError, CoreSubjectList
from app.services.core_subject_validation import codes_in_text, validate_core_subjects

CATALOG = {"CSIT111": {"cp": "6"}, "CSIT121": {"cp": "6"}}


def _subject(code="CSIT111", cp=6, **extra):
    return {"code": code, "name": "X", "valid_sessions": "Autumn", "credit_points": cp,
            "pre-requisites": "None", "co-requisites": "None", **extra}


def _validate(parsed, record=frozenset(), handbook=frozenset()):
    try:
        core = CoreSubjectList.from_llm(parsed)
    except CoreSubjectFormatError as exc:
        return exc.issues
    return validate_core_subjects(core, catalog=CATALOG, handbook_codes=set(handbook), record_codes=set(record))


def test_valid_list_has_no_issues() -> None:
    assert _validate({"subjects": [_subject(), _subject("CSIT121")]}) == []


def test_non_object_is_rejected() -> None:
    assert _validate("not json")


def test_schema_errors_are_reported_per_field() -> None:
    issues = _validate({"subjects": [_subject(cp="six")]})
    assert any("credit_points" in issue for issue in issues)


def test_duplicate_codes_rejected() -> None:
    assert any("duplicate" in issue for issue in _validate({"subjects": [_subject(), _subject()]}))


def test_unknown_code_rejected_unless_handbook_mentions_it() -> None:
    assert _validate({"subjects": [_subject("ZZZ999")]})
    assert _validate({"subjects": [_subject("ZZZ999")]}, handbook={"ZZZ999"}) == []


def test_credit_points_must_match_catalog() -> None:
    issues = _validate({"subjects": [_subject(cp=8)]})
    assert any("catalog lists 6" in issue for issue in issues)


def test_subject_already_in_record_rejected() -> None:
    assert any("already in the student record" in i for i in _validate({"subjects": [_subject()]}, record={"CSIT111"}))


def test_codes_in_text() -> None:
    assert codes_in_text("take CSIT111 and MATH255A") == {"CSIT111", "MATH255A"}


@pytest.mark.asyncio
async def test_evaluate_returns_feedback_without_calling_the_model() -> None:
    nodes = Stage1Nodes(LLMRegistry(None, {}))
    state = {
        "meta": {"degree_code": "766", "year": 2026},
        "remaining_subjects": json.dumps({"subjects": [_subject("ZZZ999")]}),
        "handbook": "",
        "raw_sols": None,
        "stage1_retry_count": 0,
    }
    out = await nodes.evaluate(state)
    assert "ZZZ999" in out["remaining_feedback"]
    assert out["stage1_retry_count"] == 1


def test_from_llm_returns_typed_subjects_with_normalised_codes() -> None:
    core = CoreSubjectList.from_llm({"subjects": [_subject("csit 111", cp="6")]})
    assert core.subjects[0].code == "CSIT111"
    assert core.subjects[0].credit_points == 6
    assert json.loads(core.to_state())["subjects"][0]["pre-requisites"] == "None"


def test_verdict_requires_the_validity_flag() -> None:
    with pytest.raises(ValueError):
        CoreEvalVerdict.model_validate({"remaining_feedback": "x"})
    assert CoreEvalVerdict(remaining_valid=False).feedback == "Invalid core subjects."
    assert CoreEvalVerdict(remaining_valid=True, remaining_feedback="x").feedback is None
