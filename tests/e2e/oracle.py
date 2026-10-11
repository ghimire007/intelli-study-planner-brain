"""Deterministic grader for a generated study plan.

The model never grades itself. Each rule below is plain arithmetic over the
student's record, the course rules and the subject catalog, so a prompt change
can only pass by producing a plan that is actually right.

Rules are HARD (must hold on every run) or SOFT (judged by pass rate across
runs, because the model varies in wording but not in what must be true).
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from app.services.course_rules import CourseRules
from app.services.prerequisite_parser import expressions_satisfied, subject_level_from_code

from tests.e2e.cases import Case, session_key
from tests.e2e.plan import PlannedSubject

PASS_GRADES = frozenset({"HD", "D", "C", "P", "PS", "CO", "S", "E"})
SUBJECT_CODE = re.compile(r"^[A-Z]{2,4}\d{3}[A-Z]?$")
MAX_SESSION_CP = 24


@dataclass(frozen=True)
class Violation:
    rule: str
    hard: bool
    detail: str


@dataclass(frozen=True)
class Held:
    code: str
    cp: int
    key: tuple[int, int]


class PlanContext:
    """Everything a rule needs, derived once from a case and its plan."""

    def __init__(self, case: Case, rules: CourseRules, catalog: dict[str, dict], plan: list[PlannedSubject]) -> None:
        self.case, self.rules, self.catalog, self.plan = case, rules, catalog, plan
        self.held = [
            Held(row.code, row.nom_cp, session_key(row.year, row.session))
            for row in case.record.rows
            if row.status == "Enrolled" or (row.status == "Complete" and row.grade in PASS_GRADES)
        ] + [Held(credit.code, credit.nom_cp, (0, 0)) for credit in case.record.specified_credit if credit.code]
        self.unspecified_cp = sum(credit.nom_cp for credit in case.record.unspecified_credit)
        self.future = [s for s in plan if session_key(s.year, s.session) > case.last_key]
        self.counted = [s for s in self.future if "excess" not in s.notes.lower()]
        self.held_codes = {item.code for item in self.held}
        self.record_codes = {row.code for row in case.record.rows}
        self.cp_by_code = {code: int(entry["cp"]) for code, entry in catalog.items() if str(entry.get("cp")).isdigit()}
        self.major_codes = _major_subjects(case.majors, rules)

    def real_codes(self, subjects: list[PlannedSubject]) -> set[str]:
        return {s.code for s in subjects if SUBJECT_CODE.match(s.code)}


def _major_subjects(majors: list[str], rules: CourseRules) -> set[str]:
    subjects: set[str] = set()
    for major in majors:
        code = rules.major_aliases.get(major.split("—")[0].strip().lower()) or rules.major_aliases.get(major.lower())
        subjects |= rules.major_core.get(code, frozenset())
    return subjects


def _is_major_placeholder(subject: PlannedSubject) -> bool:
    label = f"{subject.code} {subject.name}".lower()
    return "major" in label and not re.search(r"no[- _]?major", label)


@dataclass(frozen=True)
class Split:
    held_other: int
    planned_other: int
    required_other: int
    missing_core: set[str]
    missing_major: set[str]
    has_core_selection: bool


def split_requirements(ctx: PlanContext) -> Split:
    """Sort every counted subject into core, major or 'other' (elective / no-major path)."""
    rules = ctx.rules
    held_codes = ctx.held_codes
    planned_codes = ctx.real_codes(ctx.counted)
    present = held_codes | planned_codes

    core_used: set[str] = set()
    missing_core: set[str] = set()
    for base in rules.core_subjects:
        alternate = next((alt for alt in sorted(rules.satisfies.get(base, ())) if alt in present), None)
        if base in present:
            core_used.add(base)
        elif alternate:
            core_used.add(alternate)
        else:
            missing_core.add(base)

    # Only the first core-selection subject is core; any further one is an elective.
    selections = sorted(rules.core_selection & present, key=lambda code: next(
        (item.key for item in ctx.held if item.code == code), (9999, 0)))
    if selections:
        core_used.add(selections[0])

    major_used = ctx.major_codes & present
    capstone = rules.capstone_code
    structural = core_used | major_used | {capstone}
    major_placeholders = sum(1 for s in ctx.counted if _is_major_placeholder(s))

    held_other = ctx.unspecified_cp + sum(
        item.cp for item in ctx.held if item.code not in structural)
    planned_other = sum(
        s.cp for s in ctx.counted
        if s.code not in structural and not _is_major_placeholder(s) and s.code != capstone)

    major_cp = 6 * len(ctx.major_codes)
    required_other = rules.total_cp - 96 - major_cp
    # The 96 CP of core is 13 six-point subjects, one core selection and the capstone.
    return Split(
        held_other=held_other,
        planned_other=planned_other,
        required_other=required_other,
        missing_core=missing_core,
        missing_major=set(sorted(ctx.major_codes - present)[major_placeholders:]),
        has_core_selection=bool(selections),
    )


def _violation(rule: str, hard: bool, detail: str) -> list[Violation]:
    return [Violation(rule, hard, detail)]


def check_codes_known(ctx: PlanContext) -> list[Violation]:
    """Every code that looks like a subject code must exist; inventing one is the worst failure."""
    known = {code.upper().replace(" ", "") for code in ctx.catalog} | ctx.record_codes
    invented = sorted({s.code for s in ctx.future if SUBJECT_CODE.match(s.code) and s.code not in known})
    return _violation("codes_known", True, f"unknown subject codes: {', '.join(invented)}") if invented else []


def check_no_duplicates(ctx: PlanContext) -> list[Violation]:
    """No subject planned twice (a capstone's two parts excepted) or already passed or enrolled."""
    capstone = ctx.rules.capstone_code
    counts: dict[str, int] = defaultdict(int)
    for subject in ctx.future:
        counts[subject.code] += 1
    repeated = sorted(
        code for code, count in counts.items()
        if SUBJECT_CODE.match(code) and count > (2 if code == capstone else 1))
    replanned = sorted(code for code in counts if code in ctx.held_codes and SUBJECT_CODE.match(code))
    issues = []
    if repeated:
        issues += _violation("no_duplicates", True, f"planned more than once: {', '.join(repeated)}")
    if replanned:
        issues += _violation("no_duplicates", True, f"already passed or enrolled: {', '.join(replanned)}")
    return issues


def check_session_offered(ctx: PlanContext) -> list[Violation]:
    """A subject must be planned in a session the catalog offers it for this campus."""
    bad = []
    for subject in ctx.future:
        offerings = [
            o["session"].lower() for o in (ctx.catalog.get(subject.code) or {}).get("offerings", [])
            if o.get("campus") == ctx.case.campus
        ]
        if offerings and not any(subject.session.lower() in offering for offering in offerings):
            bad.append(f"{subject.code} in {subject.year} {subject.session}")
    return _violation("session_offered", True, "; ".join(bad)) if bad else []


def check_prerequisites(ctx: PlanContext) -> list[Violation]:
    """Prerequisites passed or planned strictly earlier; corequisites no later than the same session."""
    level_by_code = {code: subject_level_from_code(code) for code in ctx.catalog}
    sessions = sorted({session_key(s.year, s.session) for s in ctx.future})
    bad = []
    for key in sessions:
        before = ctx.held_codes | {s.code for s in ctx.future if session_key(s.year, s.session) < key}
        same = {s.code for s in ctx.future if session_key(s.year, s.session) == key}
        for subject in (s for s in ctx.future if session_key(s.year, s.session) == key):
            entry = ctx.catalog.get(subject.code)
            if not entry:
                continue
            args = (ctx.cp_by_code, level_by_code, ctx.rules.satisfies)
            if not expressions_satisfied(entry.get("prerequisites") or [], before, *args):
                bad.append(f"{subject.code} prerequisite unmet in {key[0]} {'Spring' if key[1] else 'Autumn'}")
            elif not expressions_satisfied(entry.get("corequisites") or [], before | same, *args):
                bad.append(f"{subject.code} corequisite unmet in {key[0]} {'Spring' if key[1] else 'Autumn'}")
    return _violation("prerequisites", True, "; ".join(bad)) if bad else []


def check_chronology(ctx: PlanContext) -> list[Violation]:
    """Future sessions are Autumn or Spring, listed in time order, and start after the record ends."""
    keys = []
    for subject in ctx.plan:
        if subject.session not in ("Autumn", "Spring"):
            return _violation("chronology", True, f"{subject.code} has session {subject.session!r}")
        keys.append(session_key(subject.year, subject.session))
    if keys != sorted(keys):
        return _violation("chronology", True, "sessions are not in chronological order")
    return []


def check_session_load(ctx: PlanContext) -> list[Violation]:
    load: dict[tuple[int, str], int] = defaultdict(int)
    for subject in ctx.future:
        load[(subject.year, subject.session)] += subject.cp
    heavy = [f"{year} {session} has {cp} CP" for (year, session), cp in sorted(load.items()) if cp > MAX_SESSION_CP]
    return _violation("session_load", True, "; ".join(heavy)) if heavy else []


def check_core_complete(ctx: PlanContext) -> list[Violation]:
    split = split_requirements(ctx)
    issues = []
    if split.missing_core:
        issues += _violation("core_complete", True, f"core subjects missing: {', '.join(sorted(split.missing_core))}")
    if not split.has_core_selection:
        issues += _violation("core_complete", True, "no core selection subject (CSIT213 or CSCI251)")
    capstone = ctx.rules.capstone_code
    capstone_cp = sum(item.cp for item in ctx.held if item.code == capstone) + sum(
        s.cp for s in ctx.counted if s.code == capstone)
    if capstone_cp != ctx.rules.capstone_cp:
        issues += _violation("core_complete", True, f"{capstone} totals {capstone_cp} CP, expected {ctx.rules.capstone_cp}")
    return issues


def check_major_complete(ctx: PlanContext) -> list[Violation]:
    missing = split_requirements(ctx).missing_major
    return _violation("major_complete", True, f"major subjects missing: {', '.join(sorted(missing))}") if missing else []


def check_elective_count(ctx: PlanContext) -> list[Violation]:
    """Elective / no-major CP planned is exactly what is still owed, so a plan neither stops short nor overshoots."""
    split = split_requirements(ctx)
    owed = max(0, split.required_other - split.held_other)
    if split.planned_other == owed:
        return []
    return _violation(
        "elective_count", True,
        f"planned {split.planned_other} CP of electives/no-major, owed {owed} "
        f"({split.held_other} of {split.required_other} already held)")


def check_total_cp(ctx: PlanContext) -> list[Violation]:
    """Counted credit (excess left out) adds up to exactly the degree total."""
    split = split_requirements(ctx)
    held_cp = sum(item.cp for item in ctx.held) + ctx.unspecified_cp
    excess_held = max(0, split.held_other - split.required_other)
    total = held_cp - excess_held + sum(s.cp for s in ctx.counted)
    if total == ctx.rules.total_cp:
        return []
    return _violation("total_cp", True, f"counted credit is {total} CP, degree needs {ctx.rules.total_cp}")


def check_level_cap(ctx: PlanContext) -> list[Violation]:
    at_100 = sum(item.cp for item in ctx.held if subject_level_from_code(item.code) == 100) + sum(
        s.cp for s in ctx.counted if subject_level_from_code(s.code) == 100)
    cap = ctx.rules.max_100_level_cp
    return _violation("level_cap", True, f"{at_100} CP at 100-level, cap is {cap}") if at_100 > cap else []


def check_names_match_catalog(ctx: PlanContext) -> list[Violation]:
    """Subject names come from the catalog, never from the model's memory."""
    def norm(name: str) -> str:
        return re.sub(r"[^a-z0-9]", "", re.sub(r"\(?part \d\)?", "", name.lower()))

    wrong = [
        f"{s.code} named {s.name!r}, catalog says {ctx.catalog[s.code]['title']!r}"
        for s in ctx.future
        if s.code in ctx.catalog and s.name and norm(s.name) != norm(ctx.catalog[s.code]["title"])
    ]
    return _violation("names_match_catalog", False, "; ".join(wrong)) if wrong else []


RULES: tuple[Callable[[PlanContext], list[Violation]], ...] = (
    check_codes_known, check_no_duplicates, check_session_offered, check_prerequisites,
    check_chronology, check_session_load, check_core_complete, check_major_complete,
    check_elective_count, check_total_cp, check_level_cap, check_names_match_catalog,
)


def check_plan(
    case: Case, rules: CourseRules, catalog: dict[str, dict], plan: list[PlannedSubject] | None,
) -> list[Violation]:
    """Every violation found; an empty list means the plan is right."""
    if plan is None:
        return _violation("plan_json", True, "reply has no valid ```json plan block")
    ctx = PlanContext(case, rules, catalog, plan)
    return [violation for rule in RULES for violation in rule(ctx)]

