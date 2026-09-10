"""The allowlist projection: what must never survive it, and what must.

Both halves matter. The first stops a leak; the second stops a future privacy
tweak from quietly breaking the planner by dropping something it needs.
"""
import pathlib
import re

import pytest
from app.services.enrolment import (
    KNOWN_GRADES,
    UnreadableRecord,
    parse_enrolment,
    project,
)

pytestmark = pytest.mark.smoke

RECORDS = sorted((pathlib.Path(__file__).parents[1] / "app" / "test_records").glob("*.md"))

# Identifiers that appear in the fixtures and must not reach a provider.
FORBIDDEN = [
    "OKONKWO", "WHITFIELD", "SHARMA", "MCALLISTER", "HASHIMOTO", "REYES",
    "DIALLO", "NGUYEN", "ODUYA",              # surnames
    "Rebecca", "TANG",                        # a supervisor: a third party
    "Keio", "TAFE NSW",                       # prior institutions, from Note lines
    "Effective Date", "Honours GPA",          # quasi-identifying / performance
    "Start Smart", "Consent Matters",         # supplementary qualifications
    "Leave of Absence.",                      # the Note sentence, not the status
]


def _fixtures():
    return [pytest.param(path, id=path.stem) for path in RECORDS]


def test_fixtures_are_present():
    """Guard against the corpus silently emptying and every test below passing."""
    assert len(RECORDS) >= 12


@pytest.mark.parametrize("path", _fixtures())
def test_no_identifiers_survive(path):
    projected = project(path.read_text())
    assert [word for word in FORBIDDEN if word in projected] == []


@pytest.mark.parametrize("path", _fixtures())
def test_no_student_number_survives(path):
    assert re.search(r"\b\d{7,8}\b", project(path.read_text())) is None


@pytest.mark.parametrize("path", _fixtures())
def test_no_marks_survive(path):
    """Marks are dropped structurally, so check the parsed rows, not the string.

    A two-digit mark can coincide with a credit-point value or a year, which
    makes searching the rendered text both noisy and unconvincing.
    """
    record = parse_enrolment(path.read_text())
    assert not any(hasattr(row, "mark") for row in record.rows)
    # Nominal CP is the only number on a row besides the year, and it is small.
    assert all(row.nom_cp <= 48 for row in record.rows)


@pytest.mark.parametrize("path", _fixtures())
def test_every_subject_survives(path):
    """Every code, CP, grade and status in the paste comes out the other side."""
    raw = path.read_text()
    record = parse_enrolment(raw)
    projected = project(raw)

    raw_codes = re.findall(r"\|\s*([A-Z]{2,4}\d{3}[A-Z]?)\s*\|", raw)
    assert raw_codes, "fixture has no subject codes to check"
    assert {row.code for row in record.rows} <= set(raw_codes)

    for row in record.rows:
        assert row.code in projected
        assert row.status in projected
        if row.grade:
            assert row.grade in KNOWN_GRADES


def test_failed_and_uncounted_rows_keep_their_meaning():
    """The rows a careless projection would flatten into "incomplete"."""
    everything = [parse_enrolment(path.read_text()) for path in RECORDS]
    rows = [row for record in everything for row in record.rows]

    by_status = {}
    for row in rows:
        by_status.setdefault(row.status, []).append(row)

    assert len(rows) == 161
    assert len(by_status["Withdrawn"]) == 7
    assert len(by_status["Leave of Absence"]) == 4
    assert len(by_status["Not Counted (Prior Course)"]) == 3
    assert len([row for row in rows if row.grade == "F"]) == 2

    # A prior-course row passed but must not read as ordinary completion.
    prior = by_status["Not Counted (Prior Course)"]
    assert all(row.grade in {"D", "HD"} for row in prior)
    assert all(row.status != "Complete" for row in prior)


def test_double_major_keeps_both_majors():
    record = parse_enrolment((RECORDS[0].parent / "third_year_double_major.md").read_text())
    assert record.majors == ["AIBD", "CSEC"]


def test_undeclared_major_yields_none():
    record = parse_enrolment((RECORDS[0].parent / "first_year_sem_1.md").read_text())
    assert record.majors == []


@pytest.mark.parametrize("path", _fixtures())
def test_parser_metadata_still_extractable(path):
    """The projection must still carry what sols_parser reads back out of it."""
    projected = project(path.read_text())
    record = parse_enrolment(path.read_text())
    assert f"**Course:** {record.course_code}" in projected
    assert "**Campus:** Wollongong" in projected
    assert str(min(row.year for row in record.rows)) in projected


class TestFailsClosed:
    """An unreadable paste is rejected, never passed through as raw text."""

    def test_prose_with_no_table(self):
        with pytest.raises(UnreadableRecord):
            project("Hi, I'm a second year student and I want to plan my degree.")

    def test_empty(self):
        with pytest.raises(UnreadableRecord):
            project("")

    def test_unknown_grade(self):
        with pytest.raises(UnreadableRecord, match="not a known grade"):
            project(
                "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 2025 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 78 | ZZ | Complete |\n"
            )

    def test_unknown_status(self):
        with pytest.raises(UnreadableRecord, match="not a known enrolment status"):
            project(
                "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 2025 | Autumn | Wollongong/On Campus | CSIT110 | 6 | 78 | D | Vibing |\n"
            )

    def test_misaligned_columns(self):
        with pytest.raises(UnreadableRecord, match="columns"):
            project(
                "| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |\n"
                "|---|---|---|---|---|---|---|---|\n"
                "| 2025 | Autumn | CSIT110 | 6 | D | Complete |\n"
            )

    def test_unrecognised_table_is_skipped_not_parsed(self):
        """A table we do not know contributes nothing, and cannot rescue a paste."""
        with pytest.raises(UnreadableRecord):
            project("| Code | Description |\n|---|---|\n| Start Smart | EAIS |\n")
