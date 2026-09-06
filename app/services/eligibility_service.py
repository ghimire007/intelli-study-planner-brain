"""Student subject eligibility for course 766 (and extensible to other courses)."""

from __future__ import annotations

import json
from pathlib import Path

from app.schemas.eligibility import (
    EligibleSubjectOut,
    EligibilityResult,
    StudentEligibilityInput,
)
from app.services.course_rules import CourseRules, load_course_rules
from app.services.prerequisite_parser import (
    expand_held,
    expressions_satisfied,
    normalize_code,
    subject_level_from_code,
)

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"


def _load_subjects_catalog(course: str) -> dict[str, dict]:
    path = SEEDS_DIR / "scraped" / f"subjects_{course}.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_major_code(major: str | None, rules: CourseRules) -> str | None:
    if not major or not major.strip():
        return None
    raw = major.strip()
    upper = raw.upper()
    if upper.startswith("MAJ") and upper in rules.major_core:
        return upper
    alias = rules.major_aliases.get(raw.lower())
    if alias:
        return alias
    return None


def _normalize_codes(codes: list[str]) -> set[str]:
    return {normalize_code(c) for c in codes if c and c.strip()}


def _subject_cp(subject: dict) -> int:
    try:
        return int(subject.get("cp") or 6)
    except (TypeError, ValueError):
        return 6


def _subject_level_value(subject: dict) -> int | None:
    level = (subject.get("subject_level") or "").strip()
    if level.endswith("-level") and level[:-6].isdigit():
        return int(level[:-6])
    code = subject.get("code") or ""
    return subject_level_from_code(code)


def _is_100_level(subject: dict) -> bool:
    level = _subject_level_value(subject)
    return level == 100


def _build_cp_and_level_maps(
    catalog: dict[str, dict],
    codes: set[str],
) -> tuple[dict[str, int], dict[str, int | None]]:
    cp_by_code: dict[str, int] = {}
    level_by_code: dict[str, int | None] = {}
    for code in codes:
        norm = normalize_code(code)
        entry = catalog.get(code) or catalog.get(norm) or next(
            (v for k, v in catalog.items() if normalize_code(k) == norm),
            None,
        )
        if entry:
            cp_by_code[norm] = _subject_cp(entry)
            level_by_code[norm] = _subject_level_value(entry)
        else:
            cp_by_code[norm] = 6
            level_by_code[norm] = subject_level_from_code(norm)
    return cp_by_code, level_by_code


def _total_100_level_cp(
    codes: set[str],
    catalog: dict[str, dict],
    extra_code: str | None = None,
) -> int:
    total = 0
    all_codes = set(codes)
    if extra_code:
        all_codes.add(normalize_code(extra_code))
    for code in all_codes:
        norm = normalize_code(code)
        entry = next(
            (v for k, v in catalog.items() if normalize_code(k) == norm),
            None,
        )
        if entry and _is_100_level(entry):
            total += _subject_cp(entry)
        elif not entry and subject_level_from_code(norm) == 100:
            total += 6
    return total


def _offered_in_session(subject: dict, campus: str, session: str) -> bool:
    offerings = subject.get("offerings") or []
    if not offerings:
        return False
    campus_l = campus.strip().lower()
    session_l = session.strip().lower()
    for off in offerings:
        off_campus = (off.get("campus") or "").strip().lower()
        off_session = (off.get("session") or "").strip().lower()
        if off_campus != campus_l:
            continue
        if off_session == session_l or off_session == "annual":
            return True
        if session_l in off_session:
            return True
    return False


def _replacement_blocked(
    code: str,
    completed: set[str],
    rules: CourseRules,
) -> bool:
    """Block replacement codes when the core subject they replace is already complete."""
    norm = normalize_code(code)
    for replacement, core in rules.replacement_for.items():
        if normalize_code(replacement) == norm and normalize_code(core) in expand_held(
            completed, rules.satisfies
        ):
            return True
    return False


def _exclusion_blocked(
    subject: dict,
    completed: set[str],
    rules: CourseRules,
) -> bool:
    """Block when a completed subject appears in this subject's exclusions list."""
    completed_expanded = expand_held(completed, rules.satisfies)
    for exclusion in subject.get("exclusions") or []:
        if normalize_code(exclusion) in completed_expanded:
            return True
    return False


def _in_core_or_major(
    subject_code: str,
    major_code: str | None,
    rules: CourseRules,
) -> tuple[bool, bool]:
    norm = normalize_code(subject_code)
    in_core = norm in rules.core_subjects | rules.core_selection
    in_major = False
    if major_code and major_code in rules.major_core:
        in_major = norm in rules.major_core[major_code]
    return in_core, in_major


def get_eligible_subjects(student: StudentEligibilityInput) -> EligibilityResult:
    """Return subjects the student may enrol in for the given session/campus."""
    catalog = _load_subjects_catalog(student.course)
    if not catalog:
        return EligibilityResult(eligible_subjects=[])

    try:
        rules = load_course_rules(student.course, student.campus)
    except (FileNotFoundError, ValueError):
        return EligibilityResult(eligible_subjects=[])

    completed = _normalize_codes(student.completed_subjects)
    planned = _normalize_codes(student.planned_subjects)
    major_code = resolve_major_code(student.major, rules)

    prereq_held = completed | planned
    coreq_held = completed | planned
    all_known = completed | planned
    cp_by_code, level_by_code = _build_cp_and_level_maps(catalog, all_known)

    eligible: list[EligibleSubjectOut] = []

    for code, subject in sorted(catalog.items()):
        norm = normalize_code(code)

        if norm in completed:
            continue
        if norm in planned:
            continue

        if not _offered_in_session(subject, student.campus, student.session):
            continue

        if not expressions_satisfied(
            subject.get("prerequisites") or [],
            prereq_held,
            cp_by_code,
            level_by_code,
            rules.satisfies,
        ):
            continue

        if not expressions_satisfied(
            subject.get("corequisites") or [],
            coreq_held,
            cp_by_code,
            level_by_code,
            rules.satisfies,
        ):
            continue

        if _exclusion_blocked(subject, completed, rules):
            continue

        if _replacement_blocked(norm, completed, rules):
            continue

        in_core, in_major = _in_core_or_major(norm, major_code, rules)
        if in_core and norm in completed:
            continue
        if in_major and norm in completed:
            continue
        if in_core and norm in planned:
            continue
        if in_major and norm in planned:
            continue

        if _is_100_level(subject):
            projected = _total_100_level_cp(completed | planned, catalog, extra_code=norm)
            if projected > rules.max_100_level_cp:
                continue

        eligible.append(
            EligibleSubjectOut(
                code=subject.get("code") or code,
                title=subject.get("title") or "",
                cp=_subject_cp(subject),
                subject_level=subject.get("subject_level")
                or f"{_subject_level_value(subject) or 'unknown'}-level",
                campus=student.campus,
                session=student.session,
                in_core=in_core,
                in_major=in_major,
            )
        )

    return EligibilityResult(eligible_subjects=eligible)
