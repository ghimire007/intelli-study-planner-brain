"""Rank elective candidates by keyword overlap (major or interest query)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.schemas.elective_ranking import (
    ElectivePoolPriorities,
    ElectivePriorityInput,
    ElectivePriorityResult,
    RankedElectiveOut,
)
from app.schemas.eligibility import StudentEligibilityInput
from app.services.course_rules import load_course_rules
from app.services.elective_pools import load_elective_pools, resolve_pool_candidates
from app.services.eligibility_service import get_eligible_subjects, resolve_major_code
from app.services.prerequisite_parser import normalize_code
from app.services.subject_catalog import load_subject_catalog

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"

_STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have in into is it its of on or that the
    this to was will with subject subjects students student study learning level
    credit points cp complete completed completing select selected one two three
    four five six uow university wollongong campus session autumn spring summer
    """.split()
)


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def keyword_overlap_score(subject: dict, query: str) -> float:
    """Fraction of query tokens found in the subject title + description."""
    subject_text = f"{subject.get('title') or ''} {subject.get('description') or ''}"
    subject_tokens = _tokenize(subject_text)
    query_tokens = _tokenize(query)
    if not subject_tokens or not query_tokens:
        return 0.0
    overlap = len(subject_tokens & query_tokens)
    return overlap / len(query_tokens)


def rank_subjects_by_keywords(
    catalog: dict[str, dict],
    codes: set[str],
    query: str,
    limit: int,
) -> list[tuple[str, float]]:
    scored: list[tuple[str, float]] = []
    for code in codes:
        norm = normalize_code(code)
        subject = catalog.get(code) or catalog.get(norm) or next(
            (entry for key, entry in catalog.items() if normalize_code(key) == norm),
            None,
        )
        if subject is None:
            continue
        score = keyword_overlap_score(subject, query)
        if score <= 0:
            continue
        scored.append((subject.get("code") or norm, score))
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:limit]


def _major_query(course: str, major_code: str) -> str:
    path = SEEDS_DIR / "scraped" / f"majors_{course}.json"
    if not path.exists():
        return major_code
    majors = json.loads(path.read_text(encoding="utf-8"))
    major = majors.get(major_code)
    if not major:
        return major_code
    return f"{major.get('title') or ''} {major.get('description') or ''}"


def _build_query(student: ElectivePriorityInput, major_code: str | None) -> str:
    if student.mode == "interest":
        return (student.interests or "").strip()
    if not major_code:
        return ""
    return _major_query(student.course, major_code)


def _forbidden_codes(
    rules,
    major_code: str | None,
    completed: set[str],
    planned: set[str],
) -> set[str]:
    forbidden = set(rules.core_subjects) | set(rules.core_selection) | completed | planned
    if major_code and major_code in rules.major_core:
        forbidden |= set(rules.major_core[major_code])
    return forbidden


def _lookup_subject(catalog: dict[str, dict], code: str) -> dict | None:
    norm = normalize_code(code)
    return catalog.get(code) or catalog.get(norm) or next(
        (entry for key, entry in catalog.items() if normalize_code(key) == norm),
        None,
    )


def get_elective_priorities(student: ElectivePriorityInput) -> ElectivePriorityResult:
    """Return ranked elective shortlists per pool for the planner."""
    pools_data = load_elective_pools(student.course)
    pools = pools_data.get("pools") or []
    if not pools:
        return ElectivePriorityResult(mode=student.mode, pools=[])

    try:
        rules = load_course_rules(student.course, student.campus)
    except (FileNotFoundError, ValueError):
        return ElectivePriorityResult(mode=student.mode, pools=[])

    year = int(pools_data.get("year") or 2026)
    catalog = load_subject_catalog(student.course, year=year)
    if not catalog:
        return ElectivePriorityResult(mode=student.mode, pools=[])

    major_code = resolve_major_code(student.major, rules)
    query = _build_query(student, major_code)
    if not query.strip():
        return ElectivePriorityResult(mode=student.mode, pools=[])

    completed = {normalize_code(c) for c in student.completed_subjects}
    planned = {normalize_code(c) for c in student.planned_subjects}
    forbidden = _forbidden_codes(rules, major_code, completed, planned)

    eligibility = get_eligible_subjects(
        StudentEligibilityInput(
            completed_subjects=student.completed_subjects,
            planned_subjects=student.planned_subjects,
            course=student.course,
            major=student.major,
            session=student.session,
            campus=student.campus,
        )
    )
    eligible_electives = {
        normalize_code(item.code)
        for item in eligibility.eligible_subjects
        if not item.in_core and not item.in_major
    }

    pool_results: list[ElectivePoolPriorities] = []
    for pool in pools:
        allowed = resolve_pool_candidates(pool, catalog, forbidden)
        candidates = allowed & eligible_electives
        ranked = rank_subjects_by_keywords(catalog, candidates, query, student.limit)
        pool_results.append(
            ElectivePoolPriorities(
                pool_id=pool.get("id") or "elective",
                title=pool.get("title") or "",
                cp=pool.get("cp"),
                priorities=[
                    RankedElectiveOut(
                        code=code,
                        title=(_lookup_subject(catalog, code) or {}).get("title") or "",
                        score=round(score, 4),
                    )
                    for code, score in ranked
                ],
            )
        )

    return ElectivePriorityResult(mode=student.mode, pools=pool_results)
