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
    Stage1ElectiveList,
    Stage1ElectiveSubject,
)
from app.schemas.eligibility import StudentEligibilityInput
from app.services.course_rules import load_course_rules
from app.services.elective_pools import load_elective_pools, resolve_pool_candidates
from app.services.eligibility_service import get_eligible_subjects, resolve_major_code
from app.services.prerequisite_parser import normalize_code
from app.services.subject_catalog import load_subject_catalog

SEEDS_DIR = Path(__file__).resolve().parent.parent.parent / "seeds"

from app.services.elective_pools import (
    ALLOWED_ELECTIVE_LEVELS,
    load_elective_pools,
    resolve_pool_candidates,
    subject_level,
)

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



def _subject_tokens(subject: dict) -> set[str]:
    """Collect searchable words from the subject metadata and code."""
    title = str(subject.get("title") or "")
    description = str(subject.get("description") or "")

    tokens = _tokenize(f"{title} {description}")

    code = normalize_code(str(subject.get("code") or ""))
    match = re.fullmatch(r"([A-Z]{2,8})(\d{3,4})[A-Z]?", code)

    if match:
        prefix = match.group(1).lower()
        tokens.add(prefix)
        tokens.add(code.lower())

    return tokens


def keyword_overlap_score(subject: dict, query: str) -> float:
    """Score lexical relevance, prioritising matches in subject titles."""
    query_tokens = _tokenize(query)

    if not query_tokens:
        return 0.0

    title_tokens = _tokenize(str(subject.get("title") or ""))
    description_tokens = _tokenize(
        str(subject.get("description") or "")
    )

    # Include a subject-code prefix for queries such as "CHEM electives".
    code = normalize_code(str(subject.get("code") or ""))
    match = re.fullmatch(r"([A-Z]{2,8})(\d{3,4})[A-Z]?", code)

    code_tokens: set[str] = set()
    if match:
        code_tokens.add(match.group(1).lower())

    title_matches = title_tokens & query_tokens
    description_matches = description_tokens & query_tokens
    code_matches = code_tokens & query_tokens

    query_count = len(query_tokens)

    title_score = len(title_matches) / query_count
    description_score = (
        len(description_matches - title_matches) / query_count
    )
    code_score = len(code_matches - title_matches) / query_count

    return min(
        1.0,
        title_score
        + 0.2 * description_score
        + 0.5 * code_score,
    )




def rank_subjects_by_keywords(
    catalog: dict[str, dict],
    codes: set[str],
    query: str,
    limit: int,
    *,
    min_score: float = 0.15,
) -> list[tuple[str, float]]:
    """Rank relevant undergraduate subjects by lexical relevance."""
    from app.services.elective_pools import (
        ALLOWED_ELECTIVE_LEVELS,
        subject_level,
    )

    if not query.strip() or limit <= 0:
        return []

    scored: list[tuple[str, float]] = []

    for code in codes:
        subject = _lookup_subject(catalog, code)

        if subject is None:
            continue

        if subject_level(subject) not in ALLOWED_ELECTIVE_LEVELS:
            continue

        score = keyword_overlap_score(subject, query)

        if score < min_score:
            continue

        normalized_code = normalize_code(
            str(subject.get("code") or code)
        )

        scored.append((normalized_code, score))

    # Stable tie-break; relevance remains the primary ordering.
    scored.sort(key=lambda item: (-item[1], item[0]))

    return scored[:limit]



def _major_query(course: str, major_code: str) -> str:
    """Resolve a major code to its official title and description."""
    path = SEEDS_DIR / "scraped" / f"majors_{course}.json"

    if not path.exists():
        return ""

    try:
        majors = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""

    normalized_code = normalize_code(major_code)

    major = majors.get(major_code)
    if major is None:
        major = next(
            (
                value
                for key, value in majors.items()
                if normalize_code(key) == normalized_code
            ),
            None,
        )

    if not isinstance(major, dict):
        return ""

    title = str(major.get("title") or "").strip()
    description = str(major.get("description") or "").strip()

    return " ".join(part for part in (title, description) if part)


def _build_query(student: ElectivePriorityInput) -> str:
    """Build a ranking query from explicit student preferences."""
    if student.mode == "interest":
        interests = student.interests or []

        if isinstance(interests, list):
            return ", ".join(
                str(interest).strip()
                for interest in interests
                if str(interest).strip()
            )

        return str(interests).strip()

    if student.mode == "major":
        supplied_major = str(student.major or "").strip()

        if not supplied_major:
            return ""

        resolved = _major_query(student.course, supplied_major)

        # Never silently replace a failed major-code lookup with the code
        # itself as though it were a meaningful description.
        if re.fullmatch(r"[A-Za-z]{2,8}\d{3,5}", supplied_major):
            return resolved

        return resolved or supplied_major

    return ""

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
    print("=== ELECTIVE DEBUG ===")
    print("student:", student)

    pools_data = load_elective_pools(student.course)
    print("pools_data:", pools_data)

    pools = pools_data.get("pools") or []
    print("pool count:", len(pools))

    if not pools:
        print("STOP: no pools")
        return ElectivePriorityResult(
            mode=student.mode,
            pools=[],
        )

    try:
        rules = load_course_rules(
            student.course,
            student.campus,
        )
        print("rules loaded:", bool(rules))
    except (FileNotFoundError, ValueError) as exc:
        print("STOP: course/campus rules failed:", repr(exc))
        return ElectivePriorityResult(
            mode=student.mode,
            pools=[],
        )

    year_value = pools_data.get("year")
    print("pool year:", year_value)

    if not year_value:
        print("STOP: pool year missing")
        return ElectivePriorityResult(
            mode=student.mode,
            pools=[],
        )

    year = int(year_value)

    catalog = load_subject_catalog(
        student.course,
        year=year,
    )

    print("catalog size:", len(catalog) if catalog else 0)

    if not catalog:
        print("STOP: catalog empty")
        return ElectivePriorityResult(
            mode=student.mode,
            pools=[],
        )

    major_code = resolve_major_code(
        student.major,
        rules,
    )

    print("student.major:", repr(student.major))
    print("resolved major_code:", repr(major_code))

    query = _build_query(student)

    print("query:", repr(query))

    if not query.strip():
        print("STOP: empty query")
        return ElectivePriorityResult(
            mode=student.mode,
            pools=[],
        )

    completed = {
        normalize_code(c)
        for c in student.completed_subjects
    }

    planned = {
        normalize_code(c)
        for c in student.planned_subjects
    }

    forbidden = _forbidden_codes(
        rules,
        major_code,
        completed,
        planned,
    )

    print("completed:", completed)
    print("planned:", planned)
    print("forbidden count:", len(forbidden))

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

    print(
        "eligible subject count:",
        len(eligibility.eligible_subjects),
    )

    eligible_electives = {
        normalize_code(item.code)
        for item in eligibility.eligible_subjects
        if not item.in_core
        and not item.in_major
        and subject_level(
            _lookup_subject(catalog, item.code) or {}
        ) in ALLOWED_ELECTIVE_LEVELS
    }

    print(
        "eligible_electives count:",
        len(eligible_electives),
    )

    pool_results: list[ElectivePoolPriorities] = []

    for pool in pools:
        allowed = resolve_pool_candidates(
            pool,
            catalog,
            forbidden,
        )

        candidates = allowed & eligible_electives

        print(
            "POOL:",
            pool.get("id"),
            "allowed:",
            len(allowed),
            "eligible:",
            len(eligible_electives),
            "intersection:",
            len(candidates),
        )

        ranked = rank_subjects_by_keywords(
            catalog,
            candidates,
            query,
            student.limit,
        )

        print("ranked:", ranked)

        pool_results.append(
            ElectivePoolPriorities(
                pool_id=pool.get("id") or "elective",
                title=pool.get("title") or "",
                cp=pool.get("cp"),
                priorities=[
                    RankedElectiveOut(
                        code=code,
                        title=(
                            _lookup_subject(
                                catalog,
                                code,
                            ) or {}
                        ).get("title") or "",
                        score=round(score, 4),
                    )
                    for code, score in ranked
                ],
            )
        )

    print("POOL RESULTS:", pool_results)

    return ElectivePriorityResult(
        mode=student.mode,
        pools=pool_results,
    )



def _join_requirement_list(values: list | None) -> str:
    parts = [str(item).strip() for item in (values or []) if str(item).strip()]
    return "; ".join(parts) if parts else "None"


def _cp_value(subject: dict) -> int:
    raw = subject.get("cp") if subject else None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 6


def _valid_sessions(subject: dict, campus: str) -> str:
    campus_l = campus.strip().lower()
    sessions: list[str] = []
    for offering in subject.get("offerings") or []:
        off_campus = (offering.get("campus") or "").strip().lower()
        if off_campus and off_campus != campus_l:
            continue
        session = (offering.get("session") or "").strip()
        if session and session not in sessions:
            sessions.append(session)
    return ", ".join(sessions) if sessions else "None"



def flatten_ranked_electives(
    ranking: ElectivePriorityResult,
    *,
    campus: str,
    session: str,
    course: str,
    catalog: dict[str, dict] | None = None,
) -> Stage1ElectiveList:
    """Merge pool results and globally sort by relevance."""
    from app.services.elective_pools import (
        ALLOWED_ELECTIVE_LEVELS,
        subject_level,
    )

    catalog = (
        catalog
        if catalog is not None
        else load_subject_catalog(course)
    )

    best: dict[str, tuple[float, str, str]] = {}

    for pool in ranking.pools:
        for item in pool.priorities:
            code = normalize_code(item.code)
            record = _lookup_subject(catalog, code)

            if record is None:
                continue

            if subject_level(record) not in ALLOWED_ELECTIVE_LEVELS:
                continue

            score = float(item.score)
            title = str(item.title or "").strip()
            pool_id = pool.pool_id

            previous = best.get(code)

            if previous is None or score > previous[0]:
                best[code] = (score, title, pool_id)

    subjects: list[Stage1ElectiveSubject] = []

    # Global ranking instead of first-pool-first ordering.
    ordered = sorted(
        best.items(),
        key=lambda item: (-item[1][0], item[0]),
    )

    for code, (score, ranked_title, pool_id) in ordered:
        record = _lookup_subject(catalog, code)

        if record is None:
            continue

        title = str(
            record.get("title") or ranked_title or code
        ).strip()

        cp = _cp_value(record)

        subjects.append(
            Stage1ElectiveSubject(
                code=record.get("code") or code,
                title=title,
                name=title,
                cp=cp,
                credit_points=cp,
                campus=campus,
                session=session,
                valid_sessions=_valid_sessions(record, campus),
                pool_id=pool_id,
                score=round(score, 4),
                **{
                    "pre-requisites": _join_requirement_list(
                        record.get("prerequisites")
                    ),
                    "co-requisites": _join_requirement_list(
                        record.get("corequisites")
                    ),
                },
            )
        )

    return Stage1ElectiveList(subjects=subjects)


def get_stage1_elective_list(student: ElectivePriorityInput) -> Stage1ElectiveList:
    """Rank electives then flatten to the Stage-1 list graphAPI stores."""
    ranking = get_elective_priorities(student)
    return flatten_ranked_electives(
        ranking,
        campus=student.campus,
        session=student.session,
        course=student.course,
    )
