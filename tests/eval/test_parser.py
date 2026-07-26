"""
Unit tests for the Phase 2 deterministic post-processor
(`tests/eval/parser.py`).

These tests are pure-function — no DB, no LLM, no fixtures from `conftest.py`.
They run in the default suite regardless of `--llm` flag and are marked
`smoke` so `pytest -m smoke` exercises them.
"""
from __future__ import annotations

import pytest

from tests.eval.parser import (
    EnrolmentRow,
    PASSING_GRADES,
    SUBJECT_CODE_PATTERN,
    ScheduledSubject,
    SpecifiedCredit,
    UnspecifiedCredit,
    all_completed_subject_codes,
    completed_cp_from_history,
    completed_subject_codes,
    extract_subject_codes,
    is_complete,
    parse_sols_enrolment,
    parse_specified_credits,
    parse_study_plan_table,
    parse_unspecified_credits,
    total_completed_cp,
)


pytestmark = [pytest.mark.smoke]


# ===========================================================================
# Phase 2.1: extract_subject_codes
# ===========================================================================

class TestExtractSubjectCodes:
    def test_returns_a_set(self) -> None:
        assert isinstance(extract_subject_codes("CSIT110"), set)

    def test_finds_distinct_codes(self) -> None:
        assert extract_subject_codes("CSIT110 CSIT114") == {"CSIT110", "CSIT114"}

    def test_deduplicates_repeated_codes(self) -> None:
        assert extract_subject_codes("CSIT110 CSIT110 CSIT110") == {"CSIT110"}

    def test_accepts_3_or_4_letter_prefixes(self) -> None:
        text = "ENGG100 CSIT110 CSCI235 MATH255 ISIT312 ECTE250"
        assert extract_subject_codes(text) == {
            "ENGG100", "CSIT110", "CSCI235", "MATH255", "ISIT312", "ECTE250",
        }

    def test_rejects_lowercase(self) -> None:
        assert extract_subject_codes("csit110") == set()

    def test_rejects_wrong_digit_count(self) -> None:
        assert extract_subject_codes("CSIT11 CSIT1234 CSITABC") == set()

    def test_rejects_too_few_letters(self) -> None:
        # 2 letters then 3 digits — outside the {3,4} range.
        assert extract_subject_codes("AB123") == set()

    def test_empty_input_returns_empty_set(self) -> None:
        assert extract_subject_codes("") == set()

    def test_finds_codes_in_prose(self) -> None:
        text = "I recommend enrolling in CSIT110 and then CSIT121 next session."
        assert extract_subject_codes(text) == {"CSIT110", "CSIT121"}

    def test_finds_codes_around_punctuation(self) -> None:
        text = "CSIT110, CSIT114; CSIT115. CSIT128!"
        assert extract_subject_codes(text) == {
            "CSIT110", "CSIT114", "CSIT115", "CSIT128",
        }

    def test_set_difference_for_hallucination_check(self) -> None:
        # The canonical Phase 3 use-case: reply minus (handbook ∪ sols).
        reply = "Take CSIT110, then CSIT999 (fictitious), then CSIT121."
        valid = extract_subject_codes("CSIT110, CSIT121") | extract_subject_codes("")
        invented = extract_subject_codes(reply) - valid
        assert invented == {"CSIT999"}


# ===========================================================================
# Phase 2.2: parse_study_plan_table
# ===========================================================================

WELL_FORMED_TABLE = """
Some preamble text.

**Study Plan:**

| Year | Session | Subject Code | Subject Name | CP | Notes |
|------|---------|-------------|-------------|-----|-------|
| 2026 | Autumn  | CSIT110      | Intro to CS  | 6   | New   |
| 2026 | Spring  | CSIT121      | OO Design    | 6   |       |
| 2027 | Autumn  | CSIT321      | Capstone P1  | 12  | Part 1|
| 2027 | Spring  | CSIT321      | Capstone P2  | 12  | Part 2|

Some closing text.
"""


class TestParseStudyPlanTable:
    def test_returns_a_list(self) -> None:
        assert isinstance(parse_study_plan_table(WELL_FORMED_TABLE), list)

    def test_returns_scheduled_subjects(self) -> None:
        rows = parse_study_plan_table(WELL_FORMED_TABLE)
        assert all(isinstance(r, ScheduledSubject) for r in rows)

    def test_parses_all_four_rows(self) -> None:
        rows = parse_study_plan_table(WELL_FORMED_TABLE)
        assert len(rows) == 4

    def test_first_row_fields(self) -> None:
        row = parse_study_plan_table(WELL_FORMED_TABLE)[0]
        assert row.year == 2026
        assert row.session == "Autumn"
        assert row.subject_code == "CSIT110"
        assert row.credit_points == 6

    def test_capstone_is_12cp(self) -> None:
        rows = parse_study_plan_table(WELL_FORMED_TABLE)
        capstone = [r for r in rows if r.subject_code == "CSIT321"]
        assert len(capstone) == 2
        assert all(r.credit_points == 12 for r in capstone)

    def test_capstone_spans_autumn_then_spring(self) -> None:
        rows = parse_study_plan_table(WELL_FORMED_TABLE)
        capstone = [r for r in rows if r.subject_code == "CSIT321"]
        assert [r.session for r in capstone] == ["Autumn", "Spring"]
        assert [r.year for r in capstone] == [2027, 2027]

    def test_keeps_name_and_notes_for_richer_reporting(self) -> None:
        rows = parse_study_plan_table(WELL_FORMED_TABLE)
        assert rows[0].name == "Intro to CS"
        assert rows[2].notes == "Part 1"

    def test_returns_empty_when_no_table(self) -> None:
        assert parse_study_plan_table("just some words, no table at all") == []

    def test_returns_empty_when_header_only(self) -> None:
        text = (
            "| Year | Session | Subject Code | Subject Name | CP | Notes |\n"
            "|------|---------|-------------|-------------|-----|-------|\n"
        )
        assert parse_study_plan_table(text) == []

    def test_strips_bold_markers(self) -> None:
        text = (
            "| Year | Session | Subject Code | Subject Name | CP | Notes |\n"
            "|------|---------|-------------|-------------|-----|-------|\n"
            "| **2026** | **Autumn** | **CSIT110** | Intro | **6** | |\n"
        )
        row = parse_study_plan_table(text)[0]
        assert row.year == 2026
        assert row.session == "Autumn"
        assert row.subject_code == "CSIT110"
        assert row.credit_points == 6

    def test_stops_at_first_non_pipe_line(self) -> None:
        text = (
            "| Year | Session | Subject Code | Subject Name | CP | Notes |\n"
            "|------|---------|-------------|-------------|-----|-------|\n"
            "| 2026 | Autumn | CSIT110 | Intro | 6 | |\n"
            "\n"
            "| 2027 | Spring | CSIT121 | OO | 6 | |\n"
        )
        rows = parse_study_plan_table(text)
        assert len(rows) == 1
        assert rows[0].subject_code == "CSIT110"

    def test_skips_rows_with_invalid_subject_code(self) -> None:
        text = (
            "| Year | Session | Subject Code | Subject Name | CP | Notes |\n"
            "|------|---------|-------------|-------------|-----|-------|\n"
            "| 2026 | Autumn | CSIT110 | Intro | 6 | |\n"
            "| 2026 | Autumn | TBD     | placeholder | 6 | |\n"
            "| 2026 | Spring | CSIT121 | OO | 6 | |\n"
        )
        rows = parse_study_plan_table(text)
        assert [r.subject_code for r in rows] == ["CSIT110", "CSIT121"]

    def test_skips_rows_with_invalid_year(self) -> None:
        text = (
            "| Year | Session | Subject Code | Subject Name | CP | Notes |\n"
            "|------|---------|-------------|-------------|-----|-------|\n"
            "| TBD  | Autumn | CSIT110 | Intro | 6 | |\n"
            "| 2026 | Spring | CSIT121 | OO | 6 | |\n"
        )
        rows = parse_study_plan_table(text)
        assert len(rows) == 1
        assert rows[0].subject_code == "CSIT121"

    def test_preserves_session_verbatim_for_validator_inspection(self) -> None:
        # Spec restricts plan sessions to {Autumn, Spring}, but a downstream
        # validator should be the one to flag drift — the parser must not
        # silently drop the offending row.
        text = (
            "| Year | Session | Subject Code | Subject Name | CP | Notes |\n"
            "|------|---------|-------------|-------------|-----|-------|\n"
            "| 2027 | Annual | CSIT321 | Capstone | 12 | wrong layout |\n"
        )
        rows = parse_study_plan_table(text)
        assert len(rows) == 1
        assert rows[0].session == "Annual"

    def test_handles_colon_aligned_divider(self) -> None:
        text = (
            "| Year | Session | Subject Code | Subject Name |  CP | Notes |\n"
            "|:-----|:-------:|:------------|:-----------:|----:|:------|\n"
            "| 2026 | Autumn | CSIT110 | Intro | 6 | |\n"
        )
        rows = parse_study_plan_table(text)
        assert len(rows) == 1

    def test_case_insensitive_header_match(self) -> None:
        text = (
            "| year | SESSION | subject code | name | cp | notes |\n"
            "|------|---------|--------------|------|----|-------|\n"
            "| 2026 | Autumn | CSIT110 | Intro | 6 | |\n"
        )
        rows = parse_study_plan_table(text)
        assert len(rows) == 1
        assert rows[0].subject_code == "CSIT110"

    def test_subject_code_pattern_is_exported(self) -> None:
        # Phase 3 will reuse this regex object directly.
        assert SUBJECT_CODE_PATTERN.search("CSIT110") is not None


# ===========================================================================
# Phase 3 prep: SOLS enrolment-record parsers
# ===========================================================================

SAMPLE_SOLS = """# Enrolment Record

**Student:** Test STUDENT (1234567)
**Course:** 766 — Bachelor of Computer Science

## Enrolment History

| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |
|------|---------|-----------------|--------------|--------|------|-------|--------|
| 2026 | Autumn | Wollongong/On Campus | CSCI235 | 6 | | | Enrolled |
| 2025 | Spring | Wollongong/On Campus | CSIT121 | 6 | | | Withdrawn |
| 2025 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 95 | HD | Complete |
| 2025 | Autumn | Wollongong/On Campus | CSIT114 | 6 | 72 | C | Complete |
| 2024 | Autumn | Wollongong/On Campus | CSIT115 | 6 | 42 | F | Complete |

## Specified Credit

| Course | Subject Code | Name | Level | Nom CP |
|--------|--------------|------|-------|--------|
| 766 | CSIT123 | Computing and Cyber Security Fundamentals | 1 | 6 |
| 766 | CSIT127 | Networks and Communications | 1 | 6 |

## Unspecified Credit

| Course | Level | Nom CP |
|--------|-------|--------|
| 766 | 1 | 12 |
"""


class TestParseSOLSEnrolment:
    def test_returns_a_list_of_enrolment_rows(self) -> None:
        rows = parse_sols_enrolment(SAMPLE_SOLS)
        assert isinstance(rows, list)
        assert all(isinstance(r, EnrolmentRow) for r in rows)

    def test_parses_all_history_rows(self) -> None:
        rows = parse_sols_enrolment(SAMPLE_SOLS)
        assert len(rows) == 5

    def test_completed_row_fields(self) -> None:
        rows = parse_sols_enrolment(SAMPLE_SOLS)
        complete_row = next(r for r in rows if r.subject_code == "CSIT110")
        assert complete_row.year == 2025
        assert complete_row.session == "Autumn"
        assert complete_row.campus_delivery == "Wollongong/On Campus"
        assert complete_row.nom_cp == 6
        assert complete_row.mark == 95
        assert complete_row.grade == "HD"
        assert complete_row.status == "Complete"

    def test_blank_mark_and_grade_become_none(self) -> None:
        rows = parse_sols_enrolment(SAMPLE_SOLS)
        enrolled = next(r for r in rows if r.subject_code == "CSCI235")
        assert enrolled.mark is None
        assert enrolled.grade is None
        assert enrolled.status == "Enrolled"

    def test_withdrawn_row_is_parsed(self) -> None:
        rows = parse_sols_enrolment(SAMPLE_SOLS)
        withdrawn = next(r for r in rows if r.subject_code == "CSIT121")
        assert withdrawn.status == "Withdrawn"
        assert withdrawn.grade is None

    def test_failed_row_records_F_grade(self) -> None:
        rows = parse_sols_enrolment(SAMPLE_SOLS)
        failed = next(r for r in rows if r.subject_code == "CSIT115")
        assert failed.grade == "F"
        assert failed.status == "Complete"  # F is recorded as Complete with F grade

    def test_no_enrolment_table_returns_empty(self) -> None:
        assert parse_sols_enrolment("no tables here, just prose") == []


class TestParseSpecifiedCredits:
    def test_parses_specified_rows(self) -> None:
        rows = parse_specified_credits(SAMPLE_SOLS)
        assert len(rows) == 2
        assert all(isinstance(r, SpecifiedCredit) for r in rows)

    def test_specified_fields(self) -> None:
        rows = parse_specified_credits(SAMPLE_SOLS)
        sc = next(r for r in rows if r.subject_code == "CSIT123")
        assert sc.course == "766"
        assert sc.level == 1
        assert sc.nom_cp == 6
        assert "Cyber Security" in sc.name

    def test_absent_section_returns_empty(self) -> None:
        assert parse_specified_credits("nothing here") == []


class TestParseUnspecifiedCredits:
    def test_parses_unspecified_rows(self) -> None:
        rows = parse_unspecified_credits(SAMPLE_SOLS)
        assert len(rows) == 1
        assert isinstance(rows[0], UnspecifiedCredit)
        assert rows[0].course == "766"
        assert rows[0].level == 1
        assert rows[0].nom_cp == 12

    def test_absent_section_returns_empty(self) -> None:
        assert parse_unspecified_credits("nothing here") == []

    def test_does_not_misfire_on_specified_only_text(self) -> None:
        # The Specified Credit header is 5 columns; the Unspecified anchor is
        # a full-line 3-column match, so it must not accidentally match it.
        only_specified = """
| Course | Subject Code | Name | Level | Nom CP |
|--------|--------------|------|-------|--------|
| 766 | CSIT123 | Foo | 1 | 6 |
"""
        assert parse_unspecified_credits(only_specified) == []


# ===========================================================================
# Phase 3 prep: completion helpers
# ===========================================================================

def _row(
    *,
    code: str = "CSIT110",
    year: int = 2025,
    session: str = "Autumn",
    nom_cp: int = 6,
    mark: int | None = 85,
    grade: str | None = "D",
    status: str = "Complete",
) -> EnrolmentRow:
    return EnrolmentRow(
        year=year,
        session=session,
        campus_delivery="Wollongong/On Campus",
        subject_code=code,
        nom_cp=nom_cp,
        mark=mark,
        grade=grade,
        status=status,
    )


class TestIsComplete:
    def test_complete_with_passing_grade(self) -> None:
        assert is_complete(_row(grade="HD", status="Complete"))
        assert is_complete(_row(grade="D", status="Complete"))
        assert is_complete(_row(grade="C", status="Complete"))
        assert is_complete(_row(grade="P", status="Complete"))
        assert is_complete(_row(grade="PS", status="Complete"))
        assert is_complete(_row(grade="S", status="Complete"))

    def test_failed_grade_is_not_complete(self) -> None:
        assert not is_complete(_row(grade="F", status="Complete"))

    def test_enrolled_is_not_complete(self) -> None:
        assert not is_complete(_row(grade=None, status="Enrolled"))

    def test_withdrawn_is_not_complete(self) -> None:
        assert not is_complete(_row(grade=None, status="Withdrawn"))

    def test_leave_of_absence_is_not_complete(self) -> None:
        assert not is_complete(_row(grade=None, status="Leave of Absence"))

    def test_not_counted_prior_course_is_not_complete(self) -> None:
        # Even with a passing grade, "Not Counted (Prior Course)" is excluded.
        assert not is_complete(_row(grade="D", status="Not Counted (Prior Course)"))


class TestCompletionHelpers:
    def test_completed_subject_codes_from_history(self) -> None:
        rows = parse_sols_enrolment(SAMPLE_SOLS)
        assert completed_subject_codes(rows) == {"CSIT110", "CSIT114"}

    def test_completed_cp_from_history_excludes_F(self) -> None:
        rows = parse_sols_enrolment(SAMPLE_SOLS)
        # CSIT110 (HD) + CSIT114 (C) = 12; CSIT115 (F) excluded.
        assert completed_cp_from_history(rows) == 12

    def test_all_completed_subject_codes_includes_specified(self) -> None:
        codes = all_completed_subject_codes(SAMPLE_SOLS)
        # History complete: CSIT110, CSIT114
        # Specified Credit:  CSIT123, CSIT127
        assert codes == {"CSIT110", "CSIT114", "CSIT123", "CSIT127"}

    def test_total_completed_cp_sums_history_specified_unspecified(self) -> None:
        # History complete: 12 (CSIT110 + CSIT114)
        # Specified Credit:  12 (CSIT123 + CSIT127)
        # Unspecified Credit: 12
        assert total_completed_cp(SAMPLE_SOLS) == 36

    def test_passing_grades_constant(self) -> None:
        # Stable contract: validators rely on this exact set.
        assert PASSING_GRADES == frozenset({"HD", "D", "C", "P", "PS", "S"})
