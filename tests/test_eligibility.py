"""Tests for prerequisite parsing and subject eligibility."""

from __future__ import annotations

import pytest

from app.schemas.eligibility import StudentEligibilityInput
from app.services.eligibility_service import get_eligible_subjects
from app.services.prerequisite_parser import evaluate_expression, expressions_satisfied


def _cp_levels(codes: list[str]) -> tuple[dict[str, int], dict[str, int | None]]:
    cp = {c.upper().replace(" ", ""): 6 for c in codes}
    levels = {c.upper().replace(" ", ""): int(c[-3]) * 100 for c in codes if c[-3].isdigit()}
    return cp, levels


@pytest.mark.parametrize(
    ("expr", "held", "expected"),
    [
        ("", set(), True),
        ("CSIT121", {"CSIT121"}, True),
        ("CSIT121", set(), False),
        ("CSIT110 OR CSIT111 OR ENGG100", {"CSIT111"}, True),
        (
            "(CSIT110 or CSIT111) AND (CSIT113 or CSIT123)",
            {"CSIT110", "CSIT123"},
            True,
        ),
        (
            "(CSIT110 or CSIT111) AND (CSIT113 or CSIT123)",
            {"CSIT110"},
            False,
        ),
        (
            "(CSIT121 and CSIT214) OR (ECTE250 and CSCI291)",
            {"ECTE250", "CSCI291"},
            True,
        ),
        (
            "CSIT214, and an additional 18cp 200 level CSCI/CSIT/ISIT",
            {"CSIT214", "CSCI203", "CSIT242"},
            True,
        ),
        (
            "CSIT214, and an additional 18cp 200 level CSCI/CSIT/ISIT",
            {"CSIT214", "CSCI203"},
            False,
        ),
        (
            "(CSIT110 or CSIT111) and another 18cp at 100 level",
            {"CSIT110", "CSIT123", "CSIT114", "CSIT115"},
            True,
        ),
    ],
)
def test_prerequisite_expressions(expr: str, held: set[str], expected: bool) -> None:
    cp, levels = _cp_levels(list(held))
    assert evaluate_expression(expr, held, cp, levels) is expected


def test_first_year_autumn_wollongong_includes_core_starters() -> None:
    result = get_eligible_subjects(
        StudentEligibilityInput(
            completed_subjects=[],
            planned_subjects=[],
            course="766",
            major="MAJ44204",
            session="Autumn",
            campus="Wollongong",
        )
    )
    codes = {s.code for s in result.eligible_subjects}
    assert "CSIT110" in codes
    assert "CSIT123" in codes
    assert "CSIT114" in codes


def test_completed_subject_not_eligible() -> None:
    result = get_eligible_subjects(
        StudentEligibilityInput(
            completed_subjects=["CSIT110", "CSIT123", "CSIT114"],
            planned_subjects=[],
            course="766",
            session="Autumn",
            campus="Wollongong",
        )
    )
    codes = {s.code for s in result.eligible_subjects}
    assert "CSIT110" not in codes
    assert "CSIT123" not in codes


def test_prerequisite_gated_subject() -> None:
    without = get_eligible_subjects(
        StudentEligibilityInput(
            completed_subjects=["CSIT110"],
            planned_subjects=[],
            course="766",
            session="Autumn",
            campus="Wollongong",
        )
    )
    without_codes = {s.code for s in without.eligible_subjects}

    with_prereqs = get_eligible_subjects(
        StudentEligibilityInput(
            completed_subjects=["CSIT110", "CSIT111", "CSIT123", "CSIT113"],
            planned_subjects=[],
            course="766",
            session="Spring",
            campus="Wollongong",
        )
    )
    with_codes = {s.code for s in with_prereqs.eligible_subjects}
    assert "CSCI203" not in without_codes
    assert "CSCI203" in with_codes


def test_replacement_blocked_when_core_complete() -> None:
    result = get_eligible_subjects(
        StudentEligibilityInput(
            completed_subjects=["CSIT110"],
            planned_subjects=[],
            course="766",
            session="Autumn",
            campus="Wollongong",
        )
    )
    codes = {s.code for s in result.eligible_subjects}
    assert "CSIT111" not in codes


def test_exclusion_blocks_math221_when_math121_complete() -> None:
    result = get_eligible_subjects(
        StudentEligibilityInput(
            completed_subjects=["MATH121"],
            planned_subjects=[],
            course="766",
            session="Autumn",
            campus="Wollongong",
        )
    )
    codes = {s.code for s in result.eligible_subjects}
    assert "MATH221" not in codes


def test_100_level_cap_blocks_extra_100_level() -> None:
    all_100_level_in_catalog = [
        "CSIT110",
        "CSIT111",
        "CSIT113",
        "CSIT114",
        "CSIT115",
        "CSIT121",
        "CSIT123",
        "CSIT127",
        "CSIT128",
    ]
    result = get_eligible_subjects(
        StudentEligibilityInput(
            completed_subjects=all_100_level_in_catalog,
            planned_subjects=[],
            course="766",
            session="Autumn",
            campus="Wollongong",
        )
    )
    assert not any(s.subject_level.startswith("100") for s in result.eligible_subjects)
    assert any(s.subject_level.startswith("200") for s in result.eligible_subjects)
