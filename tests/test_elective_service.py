"""Elective service: ingest subjects, build the eligible pool, fill the plan.

The study-plan step places handbook electives into placeholder slots. A subject
counts only when it was ingested, belongs to the pool, and passes the slot's
session, campus, prerequisite, corequisite, level, exclusion, and 100-level cap.
"""

from __future__ import annotations

import json

import pytest
from app.services.course_rules import CourseRules
from app.services.elective_service import (
    PlanSlot,
    build_eligible_elective_pool,
    fill_elective_slots,
    fill_plan_from_subjects,
    ingest_subjects,
)
from scripts.merge_subjects import merge_catalogs

pytestmark = pytest.mark.smoke

OPEN_POOL = {
    "id": "elective",
    "mode": "open",
    "prefixes": ["CSIT", "CSCI", "ISIT"],
    "include_general_schedule": True,
}


def _rules(**overrides) -> CourseRules:
    values = dict(
        course="766",
        campus="Wollongong",
        year=2026,
        total_cp=144,
        max_100_level_cp=60,
        capstone_code="CSIT321",
        capstone_cp=12,
        core_subjects=frozenset({"CSIT110"}),
        core_selection=frozenset(),
        replacement_for={},
        satisfies={},
        major_core={},
        major_aliases={},
    )
    values.update(overrides)
    return CourseRules(**values)


def _subject(
    code: str,
    title: str,
    *,
    level: str = "300-level",
    session: str = "Autumn",
    campus: str = "Wollongong",
    prereqs: list[str] | None = None,
    coreqs: list[str] | None = None,
    tags: list[str] | None = None,
    exclusions: list[str] | None = None,
    description: str = "",
    cp: str = "6",
    offerings: list[dict] | None = None,
) -> dict:
    return {
        "code": code,
        "title": title,
        "description": description,
        "cp": cp,
        "prerequisites": prereqs or [],
        "corequisites": coreqs or [],
        "exclusions": exclusions or [],
        "subject_level": level,
        "tags": tags or [],
        "offerings": offerings
        or [{"campus": campus, "session": session, "mode": "On-Campus"}],
    }


def _pool(
    catalog: dict[str, dict],
    *,
    pool: dict | None = None,
    forbidden: set[str] | None = None,
    completed: set[str] | None = None,
    planned: set[str] | None = None,
    session: str | None = "Autumn",
    rules: CourseRules | None = None,
) -> set[str]:
    return build_eligible_elective_pool(
        catalog,
        pool or OPEN_POOL,
        forbidden=forbidden or set(),
        completed=completed or set(),
        planned=planned or set(),
        campus="Wollongong",
        session=session,
        rules=rules or _rules(),
    )


def test_ingest_normalizes_codes_and_preserves_handbook_fields() -> None:
    catalog = ingest_subjects(
        [
            _subject(
                "csci 323",
                "Modern Artificial Intelligence",
                prereqs=["CSCI203"],
                description="Theories and algorithms in artificial intelligence.",
            )
        ]
    )
    assert list(catalog) == ["CSCI323"]
    record = catalog["CSCI323"]
    assert record["code"] == "CSCI323"
    assert record["title"] == "Modern Artificial Intelligence"
    assert record["prerequisites"] == ["CSCI203"]
    assert record["cp"] == "6"
    assert record["offerings"][0]["session"] == "Autumn"


def test_ingest_duplicate_keeps_first_body_and_unions_tags() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSCI203", "Algorithms and Data Structures", tags=["General Schedule"]),
            _subject("csci 203", "Replacement title", tags=["School of Computing", "General Schedule"]),
        ]
    )
    assert catalog["CSCI203"]["title"] == "Algorithms and Data Structures"
    assert catalog["CSCI203"]["tags"] == ["General Schedule", "School of Computing"]


def test_ingest_skips_blank_codes() -> None:
    catalog = ingest_subjects([_subject("  ", "Untitled"), {"title": "No code"}])
    assert catalog == {}


def test_merge_catalogs_unions_tags_across_sources(tmp_path) -> None:
    general = tmp_path / "subjects_general_schedule.json"
    course = tmp_path / "subjects_766.json"
    general.write_text(
        json.dumps(
            {
                "CSCI203": {
                    "code": "CSCI203",
                    "title": "Algorithms and Data Structures",
                    "tags": ["General Schedule"],
                }
            }
        ),
        encoding="utf-8",
    )
    course.write_text(
        json.dumps(
            {
                "csci 203": {
                    "code": "csci 203",
                    "title": "Other title",
                    "tags": ["School of Computing"],
                },
                "CSIT999": {"code": "CSIT999", "title": "New subject", "tags": []},
            }
        ),
        encoding="utf-8",
    )

    catalog, index = merge_catalogs(2026, tmp_path, ["766"])

    assert catalog["CSCI203"]["title"] == "Algorithms and Data Structures"
    assert catalog["CSCI203"]["tags"] == ["General Schedule", "School of Computing"]
    assert catalog["CSCI203"]["sources"] == ["general_schedule", "course_766"]
    assert catalog["CSIT999"]["title"] == "New subject"
    assert index["canonical_count"] == 2


def test_800_and_900_level_subjects_do_not_enter_the_elective_pool() -> None:
    """Postgraduate 800/900 subjects are ingested, then must stop before the pool."""
    records = [
        _subject("CSCI323", "Modern Artificial Intelligence", level="300-level"),
        _subject("CSCI803", "Research Methods", level="800-level"),
        _subject("CSCI903", "Thesis", level="900-level"),
    ]
    catalog = ingest_subjects(records)
    assert {"CSCI803", "CSCI903"} <= set(catalog)

    pool = _pool(catalog)
    assert {"CSCI803", "CSCI903"}.isdisjoint(pool), (
        f"800/900-level subjects entered at the eligible elective pool: {sorted(pool)}"
    )

    filled = fill_plan_from_subjects(
        records,
        OPEN_POOL,
        [PlanSlot(2026, "Autumn", "ELECTIVE"), PlanSlot(2026, "Autumn", "ELECTIVE")],
        completed=[],
        planned=[],
        forbidden=set(),
        campus="Wollongong",
        query="research thesis intelligence",
        rules=_rules(),
    )
    placed = {slot.code for slot in filled}
    assert {"CSCI803", "CSCI903"}.isdisjoint(placed), (
        f"800/900-level subjects entered when filling the study plan: { [slot.code for slot in filled] }"
    )


def test_open_pool_admits_ingested_school_and_general_schedule_subjects() -> None:
    catalog = ingest_subjects(
        [
            _subject("csci 323", "Modern Artificial Intelligence"),
            _subject(
                "ECON100",
                "Economic Essentials",
                level="100-level",
                tags=["General Schedule"],
            ),
            _subject("MATH121", "Discrete Mathematics", level="100-level"),
        ]
    )
    assert _pool(catalog) == {"CSCI323", "ECON100"}


def test_pool_excludes_forbidden_completed_planned_and_unmet_prerequisites() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSIT110", "Programming Fundamentals", level="100-level"),
            _subject("CSCI203", "Algorithms and Data Structures", level="200-level"),
            _subject(
                "CSCI323",
                "Modern Artificial Intelligence",
                prereqs=["CSCI203"],
            ),
            _subject("ISIT219", "Web Programming"),
        ]
    )

    without_prereq = _pool(catalog, forbidden={"CSIT110"})
    assert without_prereq == {"CSCI203", "ISIT219"}

    with_progress = _pool(
        catalog,
        forbidden={"CSIT110"},
        completed={"ISIT219"},
        planned={"CSCI203"},
    )
    assert with_progress == {"CSCI323"}


def test_named_list_requires_the_subject_to_have_been_ingested() -> None:
    catalog = ingest_subjects([_subject("CSCI323", "Modern Artificial Intelligence")])
    codes = _pool(
        catalog,
        pool={
            "mode": "named_list",
            "codes": ["CSCI323", "ISIT219", "CSIT110"],
        },
        forbidden={"CSIT110"},
    )
    assert codes == {"CSCI323"}


def test_prefix_level_pool_keeps_only_listed_levels() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSCI203", "Algorithms and Data Structures", level="200-level"),
            _subject("CSCI323", "Modern Artificial Intelligence", level="300-level"),
        ]
    )
    codes = _pool(
        catalog,
        pool={
            "mode": "prefix_level",
            "prefixes": ["CSCI", "CSIT", "ISIT"],
            "level_rules": [{"count": 1, "levels": [300]}],
        },
    )
    assert codes == {"CSCI323"}


def test_session_eligibility_requires_a_matching_offering() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSCI323", "Modern Artificial Intelligence", session="Autumn"),
            _subject(
                "CSCI347",
                "Applied Artificial Intelligence",
                session="Spring",
            ),
        ]
    )
    autumn = _pool(catalog, session="Autumn")
    assert autumn == {"CSCI323"}

    either = _pool(catalog, session=None)
    assert either == {"CSCI323", "CSCI347"}


def test_exclusion_replacement_and_100_level_cap() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSIT110", "Programming Fundamentals", level="100-level"),
            _subject("CSIT114", "System Analysis", level="100-level"),
            _subject("CSIT111", "Programming Fundamentals Alternate", level="100-level"),
            _subject(
                "CSCI318",
                "Software Engineering",
                exclusions=["CSIT110"],
            ),
            _subject(
                "ACCY111",
                "Accounting Fundamentals",
                level="100-level",
                tags=["General Schedule"],
            ),
        ]
    )
    rules = _rules(
        max_100_level_cp=12,
        replacement_for={"CSIT111": "CSIT110"},
    )
    codes = _pool(
        catalog,
        completed={"CSIT110", "CSIT114"},
        rules=rules,
    )
    assert codes == set()


def test_fill_picks_the_first_ranked_subject_offered_on_that_campus() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSCI999", "Modern Artificial Intelligence", campus="Dubai"),
            _subject("CSCI323", "Modern Artificial Intelligence"),
            _subject("CSCI347", "Applied Artificial Intelligence", session="Spring"),
        ]
    )
    filled = fill_elective_slots(
        [PlanSlot(2026, "Autumn", "ELECTIVE"), PlanSlot(2026, "Spring", "ELECTIVE")],
        ["CSCI999", "CSCI323", "CSCI347"],
        catalog,
        completed=set(),
        campus="Wollongong",
        rules=_rules(),
    )
    assert [slot.code for slot in filled] == ["CSCI323", "CSCI347"]
    assert filled[0].name == "Modern Artificial Intelligence"
    assert filled[0].cp == 6


def test_prerequisite_must_come_from_an_earlier_session() -> None:
    catalog = ingest_subjects(
        [
            _subject(
                "CSCI203",
                "Algorithms and Data Structures",
                level="200-level",
                session="Autumn",
            ),
            _subject(
                "CSCI323",
                "Modern Artificial Intelligence",
                session="Autumn",
                prereqs=["CSCI203"],
            ),
        ]
    )
    filled = fill_elective_slots(
        [
            PlanSlot(2026, "Autumn", "CSCI203", name="Algorithms and Data Structures"),
            PlanSlot(2026, "Autumn", "ELECTIVE"),
            PlanSlot(2027, "Autumn", "ELECTIVE"),
        ],
        ["CSCI323", "CSCI203"],
        catalog,
        completed=set(),
        campus="Wollongong",
        rules=_rules(),
    )
    assert [slot.code for slot in filled] == ["CSCI203", "ELECTIVE", "CSCI323"]


def test_planned_subject_satisfies_a_prerequisite_without_being_reused() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSCI203", "Algorithms and Data Structures", level="200-level"),
            _subject(
                "CSCI323",
                "Modern Artificial Intelligence",
                prereqs=["CSCI203"],
            ),
        ]
    )
    filled = fill_elective_slots(
        [PlanSlot(2027, "Autumn", "ELECTIVE")],
        ["CSCI203", "CSCI323"],
        catalog,
        completed=set(),
        planned={"CSCI203"},
        campus="Wollongong",
        rules=_rules(),
    )
    assert [slot.code for slot in filled] == ["CSCI323"]


def test_corequisite_can_be_satisfied_in_the_same_session() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSCI401", "Alpha Studio"),
            _subject("CSCI402", "Beta Studio", coreqs=["CSCI401"]),
        ]
    )
    filled = fill_elective_slots(
        [
            PlanSlot(2026, "Autumn", "ELECTIVE"),
            PlanSlot(2026, "Autumn", "ELECTIVE"),
        ],
        ["CSCI402", "CSCI401"],
        catalog,
        completed=set(),
        campus="Wollongong",
        rules=_rules(),
    )
    assert [slot.code for slot in filled] == ["CSCI401", "CSCI402"]


def test_level_constraint_leaves_the_placeholder_when_nothing_fits() -> None:
    catalog = ingest_subjects(
        [_subject("CSCI323", "Modern Artificial Intelligence", level="300-level")]
    )
    filled = fill_elective_slots(
        [PlanSlot(2026, "Autumn", "ELECTIVE", name="Elective (200-level)")],
        ["CSCI323"],
        catalog,
        completed=set(),
        campus="Wollongong",
        rules=_rules(),
    )
    assert filled[0].code == "ELECTIVE"
    assert filled[0].name == "Elective (200-level)"


def test_fill_respects_exclusion_and_100_level_cap() -> None:
    catalog = ingest_subjects(
        [
            _subject("CSIT110", "Programming Fundamentals", level="100-level"),
            _subject("CSIT114", "System Analysis", level="100-level"),
            _subject("CSCI318", "Software Engineering", exclusions=["CSIT110"]),
            _subject(
                "ACCY111",
                "Accounting Fundamentals",
                level="100-level",
                tags=["General Schedule"],
            ),
        ]
    )
    rules = _rules(max_100_level_cp=12)
    filled = fill_elective_slots(
        [PlanSlot(2026, "Autumn", "ELECTIVE")],
        ["CSCI318", "ACCY111"],
        catalog,
        completed={"CSIT110", "CSIT114"},
        campus="Wollongong",
        rules=rules,
    )
    assert filled[0].code == "ELECTIVE"


def test_pipeline_ingests_ranks_and_fills_each_elective_slot() -> None:
    records = [
        _subject("CSIT110", "Programming Fundamentals", level="100-level"),
        _subject(
            "CSCI251",
            "Artificial Intelligence Fundamentals",
            offerings=[
                {"campus": "Wollongong", "session": "Autumn"},
                {"campus": "Wollongong", "session": "Spring"},
            ],
        ),
        _subject(
            "CSCI203",
            "Algorithms and Data Structures",
            level="200-level",
            session="Autumn",
        ),
        _subject(
            "csci 323",
            "Modern Artificial Intelligence",
            session="Autumn",
            prereqs=["CSCI203"],
            description="Advanced theories and algorithms in artificial intelligence.",
        ),
        _subject(
            "CSCI347",
            "Applied Artificial Intelligence",
            session="Spring",
            prereqs=["CSIT110"],
        ),
        _subject(
            "ACCY111",
            "Accounting Fundamentals",
            level="100-level",
            tags=["General Schedule"],
        ),
    ]
    slots = [
        PlanSlot(2026, "Autumn", "CSCI203", name="Algorithms and Data Structures"),
        PlanSlot(2026, "Spring", "ELECTIVE"),
        PlanSlot(2027, "Autumn", "ELECTIVE", name="Elective (300-level)"),
    ]

    filled = fill_plan_from_subjects(
        records,
        OPEN_POOL,
        slots,
        completed=["CSIT110"],
        planned=[],
        forbidden={"CSIT110", "CSCI251"},
        campus="Wollongong",
        query="artificial intelligence",
        rules=_rules(),
    )

    assert [slot.code for slot in filled] == ["CSCI203", "CSCI347", "CSCI323"]
    assert filled[1].name == "Applied Artificial Intelligence"
    assert filled[2].name == "Modern Artificial Intelligence"
    assert filled[2].cp == 6


def test_pipeline_blank_query_does_not_invent_subjects() -> None:
    filled = fill_plan_from_subjects(
        [_subject("CSCI323", "Modern Artificial Intelligence")],
        OPEN_POOL,
        [PlanSlot(2026, "Autumn", "ELECTIVE")],
        completed=[],
        planned=[],
        forbidden=set(),
        campus="Wollongong",
        query="   ",
        rules=_rules(),
    )
    assert filled[0].code == "ELECTIVE"
