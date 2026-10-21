"""Course rules for grading, with every Core section counted.

`load_course_rules` stops at the first section titled "Core". 766 has one, but
1807 nests a Core section under each of Years 1 to 3, so the loader returns a
single core subject for it and the oracle would never ask for the other 13.
This reads the same scraped file and unions all of them, leaving app code alone.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.course_rules import (
    SCRAPED_DIR,
    CourseRules,
    _find_campus_root,
    _item_codes,
    _load_json,
    _normalize_code,
    _section_title,
    _walk_nodes,
    load_course_rules,
)


def course_rules_for(course: str, campus: str = "Wollongong") -> CourseRules:
    rules = load_course_rules(course, campus)
    root = _find_campus_root(
        _load_json(SCRAPED_DIR / f"course_{course}.json").get("structure") or [], campus
    )
    core = {
        _normalize_code(code)
        for node in _walk_nodes(root)
        if "core" in (title := _section_title(node)) and "core selection" not in title
        for code in _item_codes(node)
    }
    return replace(rules, core_subjects=frozenset(core) | rules.core_subjects)
