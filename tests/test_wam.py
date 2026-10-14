"""WAM follows the UOW rule, and the mark never reaches the LLM projection."""
import types
import uuid
from decimal import Decimal

import pytest
from app.services import agent_chat_service
from app.services.agent_chat_service import AgentChatService, _with_wam
from app.services.enrolment import UnreadableRecord, parse_enrolment, project
from app.services.wam import calculate_wam

pytestmark = pytest.mark.smoke

HEADER = (
    "**Course:** 766\n**Campus:** Wollongong\n\n"
    "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def _record(*rows: str) -> str:
    return HEADER + "\n".join(f"| {row} |" for row in rows)


def test_uow_worked_example():
    """ACCY101 65x6, MGMT203 82x6, ECON313 76x8 -> 1490 / 20 = 74.5 (from the UOW page)."""
    result = calculate_wam(_record(
        "2024 | Autumn | Wollongong/On Campus | ACCY101 | 6 | 65 | C | Complete",
        "2024 | Spring | Wollongong/On Campus | MGMT203 | 6 | 82 | D | Complete",
        "2025 | Autumn | Wollongong/On Campus | ECON313 | 8 | 76 | D | Complete",
    ))
    assert result.total_credit_points == 20
    assert result.wam == Decimal("74.50")


def test_wam_is_truncated_not_rounded():
    """74.99 is not distinction-eligible, and is never shown as 75."""
    result = calculate_wam(_record(
        "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 75 | D | Complete",
        "2024 | Autumn | Wollongong/On Campus | AAAA102 | 6 | 75 | D | Complete",
        "2024 | Autumn | Wollongong/On Campus | AAAA103 | 6 | 75 | D | Complete",
        "2024 | Autumn | Wollongong/On Campus | AAAA104 | 6 | 74 | C | Complete",
    ))
    assert result.wam == Decimal("74.75")


def test_fails_count_and_technical_fail_is_49():
    result = calculate_wam(_record(
        "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 30 | F | Failed",
        "2024 | Autumn | Wollongong/On Campus | AAAA102 | 6 | | TF | Failed",
        "2024 | Autumn | Wollongong/On Campus | AAAA103 | 6 | 80 | D | Complete",
    ))
    assert result.wam == Decimal("53.00")  # (30 + 49 + 80) / 3
    assert result.total_credit_points == 18


def test_unfinished_and_unmarked_subjects_are_not_counted():
    result = calculate_wam(_record(
        "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 70 | C | Complete",
        "2024 | Autumn | Wollongong/On Campus | AAAA102 | 6 | | | Enrolled",
        "2024 | Autumn | Wollongong/On Campus | AAAA103 | 6 | | | Withdrawn",
        "2024 | Autumn | Wollongong/On Campus | AAAA104 | 6 | 90 | HD | Not Counted (Prior Course)",
        "2024 | Autumn | Wollongong/On Campus | AAAA105 | 6 | | S | Complete",
    ))
    assert result.wam == Decimal("70.00")
    assert result.total_credit_points == 6


def test_no_graded_subjects_gives_no_wam():
    result = calculate_wam(_record("2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | | | Enrolled"))
    assert result.wam is None
    assert result.total_credit_points == 0


def test_flat_paste_is_read():
    result = calculate_wam(
        "Course: 766 Year Session Campus/ Delivery Subject Code NomCP Mark Grade Status "
        "2024 Autumn Wollongong/On Campus CSIT110 6 88 HD Complete "
        "2024 Autumn Wollongong/On Campus CSIT114 6 72 C Complete"
    )
    assert result.wam == Decimal("80.00")


def test_out_of_range_mark_is_rejected():
    with pytest.raises(UnreadableRecord, match="not a valid mark"):
        calculate_wam(_record("2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 150 | HD | Complete"))


def test_mark_never_reaches_the_llm_projection_or_a_dump():
    raw = _record("2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 83 | D | Complete")
    assert parse_enrolment(raw, keep_marks=True).rows[0].mark == 83
    assert not hasattr(parse_enrolment(raw).rows[0], "mark")
    assert "83" not in project(raw)





@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 |  | HD | Complete", "no mark"),
        ("2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 95 | F | Failed", "do not match"),
        ("2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 30 | HD | Complete", "do not match"),
        ("2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | N/A | HD | Complete", "Could not read mark"),
        ("2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 80D |  | Complete", "Could not read mark"),
    ],
    ids=["grade-without-mark", "pass-mark-on-fail", "fail-mark-on-pass-grade", "non-numeric", "glued-to-grade"],
)
def test_corrupted_rows_are_refused_not_averaged_around(row, message):
    good = "2024 | Autumn | Wollongong/On Campus | CSIT114 | 6 | 70 | C | Complete"
    with pytest.raises(UnreadableRecord, match=message):
        calculate_wam(_record(good, row))


def test_whole_mark_column_missing_is_refused():
    raw = (
        "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Grade | Status |\n|---|---|---|---|---|---|---|\n"
        "| 2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | HD | Complete |"
    )
    with pytest.raises(UnreadableRecord, match="no mark"):
        calculate_wam(raw)


def test_ungraded_results_need_no_mark():
    result = calculate_wam(_record(
        "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 70 | C | Complete",
        "2024 | Autumn | Wollongong/On Campus | AAAA102 | 6 |  | S | Complete",
    ))
    assert (result.wam, result.total_credit_points) == (Decimal("70.00"), 6)


def test_a_record_pasted_twice_is_not_double_counted():
    row = "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 80 | D | Complete"
    assert calculate_wam(_record(row, row)).total_credit_points == 6


def test_conflicting_duplicates_are_refused():
    with pytest.raises(UnreadableRecord, match="appears twice"):
        calculate_wam(_record(
            "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 80 | D | Complete",
            "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 76 | D | Complete",
        ))


def test_complete_subject_with_no_mark_and_no_grade_is_refused():
    with pytest.raises(UnreadableRecord, match="neither a mark nor a grade"):
        calculate_wam(_record(
            "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 70 | C | Complete",
            "2024 | Autumn | Wollongong/On Campus | AAAA102 | 6 |  |  | Complete",
        ))


def test_failed_subject_with_no_mark_and_no_grade_is_refused():
    with pytest.raises(UnreadableRecord, match="neither a mark nor a grade"):
        calculate_wam(_record("2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 |  |  | Failed"))


@pytest.mark.parametrize("grade", ["WH", "WD", "WS", "ND", "IPC", "IPR"])
def test_results_that_are_not_final_are_not_counted(grade):
    result = calculate_wam(_record(
        "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 70 | C | Complete",
        f"2024 | Autumn | Wollongong/On Campus | AAAA102 | 6 | 20 | {grade} | Complete",
    ))
    assert (result.wam, result.total_credit_points) == (Decimal("70.00"), 6)


def test_an_implausible_credit_point_weight_is_refused():
    with pytest.raises(UnreadableRecord, match="not a valid subject weight"):
        calculate_wam(_record("2024 | Autumn | Wollongong/On Campus | AAAA101 | 100 | 80 | D | Complete"))


GOOD = _record(
    "2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 83 | D | Complete",
    "2024 | Autumn | Wollongong/On Campus | CSIT114 | 6 | 61 | P | Complete",
)


def test_prompt_record_carries_the_wam_but_no_marks_or_grade_derived_detail():
    text = _with_wam(project(GOOD), GOOD)
    assert "72.00" in text
    assert "12 credit points" in text
    assert "83" not in text.replace("72.00", "")
    assert "61" not in text


def test_unreadable_marks_do_not_block_planning_and_the_reason_is_not_shown():
    corrupt = _record("2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 95 | F | Failed")
    text = _with_wam(project(corrupt), corrupt)
    assert "could not be calculated" in text
    assert "95" not in text


def test_record_with_no_final_marks_says_so():
    enrolled = _record("2026 | Spring | Wollongong/On Campus | CSIT121 | 6 |  |  | Enrolled")
    assert "not available yet" in _with_wam(project(enrolled), enrolled)


class _FakeGraph:
    def __init__(self):
        self.payload = None
        self.state = types.SimpleNamespace(values={"meta": {"degree_code": "766"}})

    async def ainvoke(self, payload, config=None):
        self.payload = payload

    async def aget_state(self, config):
        return self.state


class _FakeResolver:
    async def resolve(self, user, requested_model=None, session=None):
        from app.llm.config import LLMConfig
        from app.llm.registry import Provider
        return LLMConfig(provider=Provider.GEMINI, model="gemini-test", api_key="k", credential_id=None)


@pytest.fixture
def service(monkeypatch):
    graph = _FakeGraph()
    monkeypatch.setattr(agent_chat_service, "build_advisor_graph", lambda *a, **k: graph)
    monkeypatch.setattr(agent_chat_service, "get_checkpointer", lambda: None)

    async def latest(*a, **k):
        return None

    monkeypatch.setattr(agent_chat_service, "latest_reply", latest)

    class _Db:
        def add(self, row):
            pass

        async def commit(self):
            pass

        async def get(self, model, key):
            return types.SimpleNamespace(user_id="u", model="gemini-test", credential_id=None, provider="gemini")

    svc = AgentChatService(db=_Db(), user=types.SimpleNamespace(id="u"))
    svc._resolver = _FakeResolver()
    return svc, graph


async def test_start_session_puts_the_wam_in_state_and_marks_nowhere(service):
    svc, graph = service
    await svc.start_session(GOOD)
    assert "72.00" in graph.payload["raw_sols"]
    sent = graph.payload["raw_sols"] + "".join(m.content for m in graph.payload["messages"])
    assert "83" not in sent.replace("72.00", "")


async def test_pasting_a_new_record_mid_chat_replaces_the_wam(service):
    svc, graph = service
    newer = _record("2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 90 | HD | Complete")
    await svc.continue_session(uuid.uuid4(), newer)
    assert "90.00" in graph.payload["raw_sols"]
