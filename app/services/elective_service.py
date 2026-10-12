"""Place handbook electives into a study plan.

Three steps, all pure:

1. Ingest subject records into a catalog keyed by subject code.
2. Build the eligible pool: handbook pool rules, minus core, major, completed,
   and planned subjects, then session, prerequisite, exclusion, and credit-point
   checks.
3. Fill elective placeholders in plan order. Rank is a preference. A higher
   ranked subject is skipped when the slot's session, campus, level, or rules
   reject it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.course_rules import CourseRules
from app.services.elective_pools import resolve_pool_candidates
from app.services.elective_ranking import rank_subjects_by_keywords
from app.services.eligibility_service import (
    _exclusion_blocked,
    _is_100_level,
    _offered_in_session,
    _replacement_blocked,
    _subject_cp,
    _subject_level_value,
    _total_100_level_cp,
)
from app.services.prerequisite_parser import (
    expressions_satisfied,
    normalize_code,
    subject_level_from_code,
)

_PLACEHOLDER_RE = re.compile(r"^(?:elective|tbd)\b", re.IGNORECASE)
_LEVEL_RE = re.compile(r"\b(100|200|300)\s*-?\s*(?:level|lv)\b", re.IGNORECASE)
_SESSION_RANK = {"autumn": 0, "spring": 1, "summer": 2}


@dataclass(frozen=True)
class PlanSlot:
    """One study-plan row. ``ELECTIVE`` and ``TBD`` codes are placeholders."""

    year: int
    session: str
    code: str
    cp: int = 6
    name: str = ""


def is_elective_placeholder(code: str) -> bool:
    return bool(_PLACEHOLDER_RE.match((code or "").strip()))


def ingest_subjects(records: list[dict]) -> dict[str, dict]:
    """Normalize subject records into a catalog keyed by subject code.

    The first record for a code keeps its body. Later records only add tags
    that the first record did not already carry.
    """
    catalog: dict[str, dict] = {}
    for record in records:
        code = normalize_code(str(record.get("code") or ""))
        if not code:
            continue
        incoming = dict(record)
        incoming["code"] = code
        incoming["tags"] = list(dict.fromkeys(tag for tag in (incoming.get("tags") or []) if tag))
        existing = catalog.get(code)
        if existing is None:
            catalog[code] = incoming
            continue
        tags = list(existing.get("tags") or [])
        for tag in incoming["tags"]:
            if tag not in tags:
                tags.append(tag)
        existing["tags"] = tags
    return catalog


def build_eligible_elective_pool(
    catalog: dict[str, dict],
    pool: dict,
    *,
    forbidden: set[str],
    completed: set[str],
    planned: set[str],
    campus: str,
    session: str | None,
    rules: CourseRules,
) -> set[str]:
    """Subjects from ``pool`` the student may take, given progress so far.

    ``session=None`` keeps every offering. A session value keeps only subjects
    offered then, on ``campus``. Prerequisites are judged against completed and
    planned subjects, not against rows later in a study plan.
    """
    blocked = _normalize_set(forbidden | set(completed) | set(planned))
    held = _normalize_set(set(completed) | set(planned))
    cp_by_code, level_by_code = _requirement_maps(catalog, held)
    eligible: set[str] = set()

    for code in resolve_pool_candidates(pool, catalog, blocked):
        subject = _lookup(catalog, code)
        if subject is None:
            continue
        norm = normalize_code(subject.get("code") or code)
        if _postgraduate_level(subject):
            continue
        if session is not None and not _offered_in_session(subject, campus, session):
            continue
        if not _rules_allow(
            subject,
            norm,
            held=held,
            prereq_held=held,
            coreq_held=held,
            catalog=catalog,
            cp_by_code=cp_by_code,
            level_by_code=level_by_code,
            coreq_cp=cp_by_code,
            coreq_levels=level_by_code,
            rules=rules,
        ):
            continue
        eligible.add(norm)
    return eligible


def fill_elective_slots(
    slots: list[PlanSlot],
    ranked_codes: list[str],
    catalog: dict[str, dict],
    *,
    completed: set[str],
    campus: str,
    rules: CourseRules,
    planned: set[str] | None = None,
) -> list[PlanSlot]:
    """Replace elective placeholders, walking the plan in calendar order.

    Prerequisites must already be completed, planned, or sitting in an earlier
    session. Corequisites may sit in the same session. The first ranked subject
    that passes wins; a slot with no match is left unchanged.
    """
    planned_codes = planned or set()
    filled = list(slots)
    used = _normalize_set(set(completed) | set(planned_codes))
    for slot in filled:
        if not is_elective_placeholder(slot.code):
            used.add(normalize_code(slot.code))

    order = sorted(range(len(filled)), key=lambda index: (_when(filled[index]), index))
    for index in order:
        slot = filled[index]
        if not is_elective_placeholder(slot.code):
            continue
        chosen = _first_fit(
            filled,
            index,
            ranked_codes,
            catalog,
            completed=set(completed),
            planned=set(planned_codes),
            campus=campus,
            rules=rules,
            used=used,
        )
        if chosen is None:
            continue
        subject, norm = chosen
        filled[index] = PlanSlot(
            year=slot.year,
            session=slot.session,
            code=subject.get("code") or norm,
            cp=_subject_cp(subject),
            name=(subject.get("title") or slot.name or norm).strip(),
        )
        used.add(norm)
    return filled


def fill_plan_from_subjects(
    records: list[dict],
    pool: dict,
    slots: list[PlanSlot],
    *,
    completed: list[str],
    planned: list[str],
    forbidden: set[str],
    campus: str,
    query: str,
    rules: CourseRules,
    limit: int = 25,
) -> list[PlanSlot]:
    """Ingest subjects, rank the handbook pool, and fill elective slots.

    Pool membership ignores the plan timeline, so a subject whose prerequisite
    is an earlier plan row can still be ranked. Slot checks decide whether that
    prerequisite is actually in place. An empty query ranks nothing.
    """
    catalog = ingest_subjects(records)
    blocked = _normalize_set(set(forbidden) | set(completed) | set(planned))
    for slot in slots:
        if not is_elective_placeholder(slot.code):
            blocked.add(normalize_code(slot.code))
    candidates = {
        code
        for code in resolve_pool_candidates(pool, catalog, blocked)
        if not _postgraduate_level(_lookup(catalog, code) or {})
    }
    ranked = rank_subjects_by_keywords(catalog, candidates, query, limit)
    return fill_elective_slots(
        slots,
        [code for code, _score in ranked],
        catalog,
        completed=set(completed),
        planned=set(planned),
        campus=campus,
        rules=rules,
    )


def _postgraduate_level(subject: dict) -> bool:
    level = _subject_level_value(subject)
    return level is not None and level >= 800


def _normalize_set(codes: set[str]) -> set[str]:
    return {normalize_code(code) for code in codes if code and str(code).strip()}


def _lookup(catalog: dict[str, dict], code: str) -> dict | None:
    norm = normalize_code(code)
    if code in catalog:
        return catalog[code]
    if norm in catalog:
        return catalog[norm]
    for key, entry in catalog.items():
        if normalize_code(key) == norm or normalize_code(str(entry.get("code") or "")) == norm:
            return entry
    return None


def _requirement_maps(
    catalog: dict[str, dict],
    codes: set[str],
) -> tuple[dict[str, int], dict[str, int | None]]:
    cp_by_code: dict[str, int] = {}
    level_by_code: dict[str, int | None] = {}
    for code in codes:
        norm = normalize_code(code)
        subject = _lookup(catalog, norm)
        if subject is None:
            cp_by_code[norm] = 6
            level_by_code[norm] = subject_level_from_code(norm)
            continue
        cp_by_code[norm] = _subject_cp(subject)
        level_by_code[norm] = _subject_level_value(subject)
    return cp_by_code, level_by_code


def _when(slot: PlanSlot) -> tuple[int, int]:
    return (slot.year, _SESSION_RANK.get(slot.session.strip().lower(), 9))


def _slot_level(slot: PlanSlot) -> int | None:
    match = _LEVEL_RE.search(f"{slot.code} {slot.name}")
    if not match:
        return None
    return int(match.group(1))


def _held(
    slots: list[PlanSlot],
    index: int,
    completed: set[str],
    planned: set[str],
    *,
    include_same_session: bool,
) -> set[str]:
    current = _when(slots[index])
    held = _normalize_set(set(completed) | set(planned))
    for position, slot in enumerate(slots):
        if position == index or is_elective_placeholder(slot.code):
            continue
        when = _when(slot)
        if when < current or (include_same_session and when == current):
            held.add(normalize_code(slot.code))
    return held


def _rules_allow(
    subject: dict,
    code: str,
    *,
    held: set[str],
    prereq_held: set[str],
    coreq_held: set[str],
    catalog: dict[str, dict],
    cp_by_code: dict[str, int],
    level_by_code: dict[str, int | None],
    coreq_cp: dict[str, int],
    coreq_levels: dict[str, int | None],
    rules: CourseRules,
) -> bool:
    if not expressions_satisfied(
        subject.get("prerequisites") or [],
        prereq_held,
        cp_by_code,
        level_by_code,
        rules.satisfies,
    ):
        return False
    if not expressions_satisfied(
        subject.get("corequisites") or [],
        coreq_held,
        coreq_cp,
        coreq_levels,
        rules.satisfies,
    ):
        return False
    if _exclusion_blocked(subject, held, rules):
        return False
    if _replacement_blocked(code, held, rules):
        return False
    if _is_100_level(subject):
        projected = _total_100_level_cp(held, catalog, extra_code=code)
        if projected > rules.max_100_level_cp:
            return False
    return True


def _first_fit(
    slots: list[PlanSlot],
    index: int,
    ranked_codes: list[str],
    catalog: dict[str, dict],
    *,
    completed: set[str],
    planned: set[str],
    campus: str,
    rules: CourseRules,
    used: set[str],
) -> tuple[dict, str] | None:
    slot = slots[index]
    wanted_level = _slot_level(slot)
    prior = _held(slots, index, completed, planned, include_same_session=False)
    through = _held(slots, index, completed, planned, include_same_session=True)
    scheduled = _normalize_set(set(completed) | set(planned))
    for row in slots:
        if not is_elective_placeholder(row.code):
            scheduled.add(normalize_code(row.code))
    prior_cp, prior_levels = _requirement_maps(catalog, prior)
    through_cp, through_levels = _requirement_maps(catalog, through)

    for code in ranked_codes:
        subject = _lookup(catalog, code)
        if subject is None:
            continue
        norm = normalize_code(subject.get("code") or code)
        if norm in used:
            continue
        if wanted_level is not None and _subject_level_value(subject) != wanted_level:
            continue
        if not _offered_in_session(subject, campus, slot.session):
            continue
        if not _rules_allow(
            subject,
            norm,
            held=scheduled,
            prereq_held=prior,
            coreq_held=through,
            catalog=catalog,
            cp_by_code=prior_cp,
            level_by_code=prior_levels,
            coreq_cp=through_cp,
            coreq_levels=through_levels,
            rules=rules,
        ):
            continue
        return subject, norm
    return None
