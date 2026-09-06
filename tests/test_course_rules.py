"""Tests that course rules load from scraped JSON + overrides."""

from __future__ import annotations

from app.services.course_rules import load_course_rules

EXPECTED_WOLLONGONG_CORE = {
    "CSIT110",
    "CSIT123",
    "CSIT114",
    "CSIT115",
    "CSIT121",
    "CSIT127",
    "CSIT128",
    "CSCI235",
    "CSIT214",
    "CSIT205",
    "CSCI203",
    "CSIT226",
    "CSIT314",
}


def test_load_course_rules_wollongong_core() -> None:
    rules = load_course_rules("766", "Wollongong")
    assert rules.core_subjects == EXPECTED_WOLLONGONG_CORE
    assert rules.core_selection == {"CSCI251", "CSIT213"}
    assert rules.capstone_code == "CSIT321"
    assert rules.capstone_cp == 12
    assert rules.total_cp == 144
    assert rules.max_100_level_cp == 60


def test_load_course_rules_equivalencies_from_overrides() -> None:
    rules = load_course_rules("766", "Wollongong")
    assert rules.replacement_for["CSIT111"] == "CSIT110"
    assert "CSIT111" in rules.satisfies["CSIT110"]


def test_load_course_rules_major_core_from_majors_json() -> None:
    rules = load_course_rules("766", "Wollongong")
    assert rules.major_core["MAJ44204"] == {"CSCI218", "CSCI316", "CSCI323", "ISIT312"}
    assert rules.major_aliases["cyber security"] == "MAJ40516"


def test_load_course_rules_campus_specific() -> None:
    woll = load_course_rules("766", "Wollongong")
    singapore = load_course_rules("766", "Singapore Institute of Management")
    assert "CSIT110" in woll.core_subjects
    assert "CSIT111" in singapore.core_subjects
    assert woll.core_subjects != singapore.core_subjects
