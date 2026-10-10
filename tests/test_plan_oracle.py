"""The plan oracle grades a plan correctly, so the live accuracy suite can trust it.

Case bcs_13 is a last-year, no-major student who still owes CSIT314, the
capstone and 30 CP of electives: 48 CP over two sessions.
"""
from __future__ import annotations

import pytest
from app.services.course_rules import load_course_rules
from app.services.subject_catalog import load_subject_catalog

from tests.e2e.cases import load_cases
from tests.e2e.oracle import PlanContext, check_plan, split_requirements
from tests.e2e.plan import PlannedSubject, parse_plan
from tests.e2e.test_accuracy import newly_broken

pytestmark = pytest.mark.smoke

CASES = {case.id: case for case in load_cases()}
RULES = load_course_rules("766", "Wollongong")
CATALOG = load_subject_catalog("766")

GOOD = [
    (2027, "Autumn", "CSIT314", 6), (2027, "Autumn", "CSIT321", 6),
    (2027, "Autumn", "CSCI316", 6), (2027, "Autumn", "CSCI323", 6),
    (2027, "Spring", "CSIT321", 6), (2027, "Spring", "CSCI218", 6),
    (2027, "Spring", "CSCI262", 6), (2027, "Spring", "CSCI336", 6),
]


def plan(*entries: tuple[int, str, str, int]) -> list[PlannedSubject]:
    return [
        PlannedSubject(year, session, code, (CATALOG.get(code) or {}).get("title", code), cp, "")
        for year, session, code, cp in entries
    ]


def rules_broken(entries, case_id: str = "bcs_13") -> set[str]:
    return {v.rule for v in check_plan(CASES[case_id], RULES, CATALOG, plan(*entries))}


def test_correct_plan_has_no_violations() -> None:
    assert check_plan(CASES["bcs_13"], RULES, CATALOG, plan(*GOOD)) == []


def test_missing_json_block_is_a_violation() -> None:
    assert [v.rule for v in check_plan(CASES["bcs_13"], RULES, CATALOG, parse_plan("no plan here"))] == ["plan_json"]


def test_parse_plan_reads_the_last_json_block() -> None:
    reply = (
        'text ```json\n{"plan": []}\n``` more text ```json\n{"plan": [{"year": "2027", "sessions": '
        '[{"session": "autumn", "subjects": [{"code": "csit 314", "name": "X", "cp": 6}]}]}]}\n```'
    )
    assert parse_plan(reply) == [PlannedSubject(2027, "Autumn", "CSIT314", "X", 6, "")]


def test_invented_subject_code_is_caught() -> None:
    assert "codes_known" in rules_broken([*GOOD[:-1], (2027, "Spring", "ISIT317", 6)])


def test_extra_elective_is_caught() -> None:
    broken = rules_broken([*GOOD, (2028, "Autumn", "CSCI334", 6)])
    assert {"elective_count", "total_cp"} <= broken


def test_missing_elective_is_caught() -> None:
    assert "elective_count" in rules_broken(GOOD[:-1])


def test_missing_core_subject_is_caught() -> None:
    assert "core_complete" in rules_broken(GOOD[1:])


def test_capstone_must_total_twelve_credit_points() -> None:
    assert "core_complete" in rules_broken([e for e in GOOD if e[2] != "CSIT321" or e[1] == "Autumn"])


def test_subject_in_a_session_it_is_not_offered_is_caught() -> None:
    swapped = [(2027, "Spring", code, cp) if code == "CSCI316" else (y, s, code, cp) for y, s, code, cp in GOOD]
    assert "session_offered" in rules_broken(swapped)


def test_corequisite_planned_later_is_caught() -> None:
    # CSIT321 needs CSIT314 in the same session or earlier.
    late = [(2028, "Autumn", code, cp) if code == "CSIT314" else (y, s, code, cp) for y, s, code, cp in GOOD]
    assert "prerequisites" in rules_broken(late)


def test_prerequisite_planned_in_the_same_session_is_caught() -> None:
    # CSCI316 needs CSCI203, which bcs_25 has not taken: the same session is too early, a later one is fine.
    same = [(2026, "Spring", "CSCI203", 6), (2026, "Spring", "CSCI316", 6)]
    later = [(2026, "Spring", "CSCI203", 6), (2027, "Autumn", "CSCI316", 6)]
    assert "prerequisites" in rules_broken(same, "bcs_25")
    assert "prerequisites" not in rules_broken(later, "bcs_25")


def test_replanning_a_passed_subject_is_caught() -> None:
    assert "no_duplicates" in rules_broken([*GOOD[:-1], (2027, "Spring", "CSIT110", 6)])


def test_overloaded_session_is_caught() -> None:
    assert "session_load" in rules_broken([(2027, "Autumn", code, cp) for _, _, code, cp in GOOD])


def test_sessions_out_of_order_are_caught() -> None:
    assert "chronology" in rules_broken(GOOD[4:] + GOOD[:4])


def test_wrong_subject_name_is_soft() -> None:
    renamed = plan(*GOOD)
    renamed[0] = PlannedSubject(2027, "Autumn", "CSIT314", "AI and Society", 6, "")
    violations = check_plan(CASES["bcs_13"], RULES, CATALOG, renamed)
    assert [(v.rule, v.hard) for v in violations] == [("names_match_catalog", False)]


def test_failed_and_withheld_results_do_not_count_as_held() -> None:
    for case_id in ("bcs_25", "bcs_27", "bcs_28"):
        assert "CSIT121" in split_requirements(PlanContext(CASES[case_id], RULES, CATALOG, [])).missing_core


def test_second_core_selection_counts_as_an_elective() -> None:
    held = split_requirements(PlanContext(CASES["bcs_13"], RULES, CATALOG, plan(*GOOD)))
    extra = split_requirements(PlanContext(CASES["bcs_13"], RULES, CATALOG, plan(*GOOD, (2028, "Autumn", "CSCI251", 6))))
    assert extra.planned_other == held.planned_other + 6


def test_baseline_excuses_known_failures_only() -> None:
    from tests.e2e.oracle import Violation

    hard, soft = Violation("total_cp", True, "x"), Violation("names_match_catalog", False, "y")
    assert newly_broken("never_in_baseline", [[hard], []])[0].startswith("total_cp (1/2 runs)")
    assert newly_broken("never_in_baseline", [[soft], []]) == []
    assert newly_broken("never_in_baseline", [[soft], [soft]])[0].startswith("names_match_catalog")
