"""WAM follows the UOW rule, and the mark never reaches the LLM projection."""
import uuid
from decimal import Decimal

import httpx
import pytest
from app.main import app
from app.services.enrolment import UnreadableRecord, parse_enrolment, project
from app.services.wam import calculate_wam, summarise_for_chat

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


def test_chat_summary_has_the_wam_but_no_subject_level_data():
    result = calculate_wam(_record(
        "2024 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 83 | D | Complete",
        "2024 | Autumn | Wollongong/On Campus | CSIT114 | 6 | 61 | P | Complete",
    ))
    summary = summarise_for_chat(result)
    assert "72.00" in summary
    assert "12 credit points" in summary
    for leaked in ("CSIT110", "CSIT114", "83", "61"):
        assert leaked not in summary


async def test_linked_endpoint_records_summary_on_the_owned_session(monkeypatch):
    from app.api.deps import get_current_user
    from app.core.database import get_db

    calls = []

    async def fake_record(self, session_id, result):
        calls.append((session_id, result.wam))

    monkeypatch.setattr("app.services.agent_chat_service.AgentChatService.record_wam", fake_record)
    app.dependency_overrides[get_current_user] = lambda: object()
    app.dependency_overrides[get_db] = lambda: None
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/v1/wam/6f1c1f0e-0000-4000-8000-000000000000",
                json={"enrolment_record": _record(
                    "2024 | Autumn | Wollongong/On Campus | AAAA101 | 6 | 80 | D | Complete")},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert calls == [(uuid.UUID("6f1c1f0e-0000-4000-8000-000000000000"), Decimal("80.00"))]


async def test_linked_endpoint_requires_login():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/wam/6f1c1f0e-0000-4000-8000-000000000000", json={"enrolment_record": "x"}
        )
    assert response.status_code == 401
