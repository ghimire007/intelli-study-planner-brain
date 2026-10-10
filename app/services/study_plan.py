"""Validate provider output against checked-in handbook data and render one plan."""
from __future__ import annotations

import json
import re
from collections import defaultdict

from app.services.course_rules import SCRAPED_DIR, load_course_rules
from app.services.elective_pools import load_elective_pools, resolve_pool_candidates
from app.services.eligibility_service import resolve_major_code
from app.services.enrolment import EnrolmentRecord, parse_enrolment
from app.services.prerequisite_parser import (
    expand_held,
    normalize_code,
    split_top_level,
    subject_level_from_code,
)
from app.services.subject_catalog import load_subject_catalog
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class PlanGenerationError(ValueError):
    """A draft is incomplete or could not be verified; never publish it as a plan."""


class Subject(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    code: str = Field(pattern=r"^[A-Z]{2,5}\d{3}[A-Z]?$")
    name: str = Field(min_length=1)
    cp: int = Field(gt=0, le=48)
    notes: str


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session: str = Field(min_length=1)
    subjects: list[Subject] = Field(min_length=1)


class Year(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    year: str = Field(pattern=r"^(19|20)\d{2}$")
    sessions: list[Session] = Field(min_length=1)


class StudyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    plan: list[Year]


SESSION_ORDER = {"Summer": 0, "Annual": 1, "Autumn": 2, "Winter": 3, "Spring": 4}
PASS_GRADES = {"HD", "D", "C", "P", "PS", "CO", "S", "E"}


def _key(year, session):
    if session not in SESSION_ORDER:
        raise PlanGenerationError(f"Unsupported teaching session {session!r}. Confirm the teaching calendar before planning.")
    return int(year), SESSION_ORDER[session]


def parse_plan(text: str, *, allow_empty: bool = False) -> StudyPlan:
    blocks = re.findall(r"```json\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if len(blocks) > 1:
        raise PlanGenerationError("The model returned multiple plan JSON blocks. Regenerate one complete plan.")
    try:
        parsed = StudyPlan.model_validate(json.loads(blocks[0] if blocks else text))
        if not parsed.plan and not allow_empty:
            raise ValueError("An empty plan is not a complete output")
        return parsed
    except (ValueError, ValidationError) as exc:
        raise PlanGenerationError("The model did not return complete valid study-plan JSON. Please regenerate the plan.") from exc


def plan_sources(state: dict) -> tuple[dict, object, set[str], list[dict]]:
    meta = state.get("meta") or {}
    try:
        rules = load_course_rules(meta["degree_code"], meta["campus"])
        catalog = {normalize_code(k): v for k, v in load_subject_catalog(rules.course).items()}
        course = json.loads((SCRAPED_DIR / f"course_{rules.course}.json").read_text())
    except (KeyError, FileNotFoundError, ValueError) as exc:
        raise PlanGenerationError("Course rules are unavailable. Confirm your degree code and campus, then load its handbook.") from exc
    majors = meta.get("majors")
    if majors is None:
        majors = [meta.get("major")] if meta.get("major") else []
    if isinstance(majors, str):
        majors = [majors]
    required = set(rules.core_subjects) | {rules.capstone_code}
    for major in majors:
        code = resolve_major_code(major, rules)
        if code is None:
            raise PlanGenerationError("Confirm a handbook-listed major (or explicitly confirm no major) before generating a plan.")
        required.update(rules.major_core[code])
    if rules.major_core and not majors:
        raise PlanGenerationError("Confirm your major before generating a complete degree plan.")
    choices = []

    def walk(nodes):
        for node in nodes:
            title = (node.get("title") or "").lower()
            if "dean's scholar component" in title:
                choices.append({"cp": int(node["cp"]), "codes": [x["code"] for x in node.get("items", [])]})
            walk(node.get("children") or [])

    walk(course.get("structure") or [])
    return catalog, rules, required, choices


def record_for(state: dict) -> EnrolmentRecord:
    """The student's record; a student with no enrolment yet has an empty one."""
    raw = state.get("raw_sols")
    if not raw or raw == "no enrolment yet":
        return EnrolmentRecord(
            course_code=None, campus=None, majors=[], rows=[], specified_credit=[], unspecified_credit=[]
        )
    return parse_enrolment(raw)


def merge_record_history(text: str, state: dict) -> str:
    """Build immutable history in code; a provider proposes future placements only."""
    draft = parse_plan(text, allow_empty=True)
    record = record_for(state)
    catalog, _, _, _ = plan_sources(state)
    historical_keys = {(str(r.year), r.session, r.code) for r in record.rows}
    locked_codes = {r.code for r in record.rows if r.status == "Enrolled" or (r.status == "Complete" and r.grade in PASS_GRADES)}
    grouped = defaultdict(list)
    for row in record.rows:
        source = catalog.get(row.code)
        if source is None or not source.get("title"):
            raise PlanGenerationError(f"No authoritative subject data for recorded {row.code}. Refresh the handbook data.")
        grouped[(str(row.year), row.session)].append(Subject(code=row.code, name=source["title"], cp=row.nom_cp, notes=""))
    for year in draft.plan:
        for session in year.sessions:
            for subject in session.subjects:
                if (year.year, session.session, subject.code) in historical_keys or subject.code in locked_codes:
                    continue
                grouped[(year.year, session.session)].append(subject)
    years = defaultdict(list)
    for (year, session), subjects in sorted(grouped.items(), key=lambda item: _key(*item[0])):
        years[year].append(Session(session=session, subjects=subjects))
    plan = StudyPlan(plan=[Year(year=year, sessions=sessions) for year, sessions in years.items()])
    return plan.model_dump_json()


def requirement_satisfied(expression: str, held: set[str], catalog: dict, satisfies: dict) -> bool:
    """Evaluate supported subject/CP requirements; unknown prose never implies a pass."""
    text = expression.strip().rstrip(".")
    if not text or text.casefold() == "none":
        return True
    while text.startswith("(") and text.endswith(")"):
        depth = 0
        entire = True
        for index, char in enumerate(text):
            depth += (char == "(") - (char == ")")
            if depth == 0 and index != len(text) - 1:
                entire = False
                break
        if not entire:
            break
        text = text[1:-1].strip()
    parts = split_top_level(text, " or ")
    if len(parts) > 1:
        results = [requirement_satisfied(p, held, catalog, satisfies) for p in parts]
        return any(results)
    parts = split_top_level(text, " and ")
    if len(parts) > 1:
        return all(requirement_satisfied(p, held, catalog, satisfies) for p in parts)
    if re.fullmatch(r"[A-Z]{2,5}\s?\d{3}[A-Z]?", text, flags=re.I):
        return normalize_code(text) in expand_held(held, satisfies)
    cp = re.fullmatch(
        r"(?:a minimum of |minimum of |at least |completion of |completed |another )?(\d+)\s*(?:cp|credit points?)"
        r"(?:\s+(?:of|at|in|from)\s+(?:(CSCI/CSIT/ISIT|CSCI/CSIT|CSCI|CSIT|ISIT)\s+)?(100|200|300)[ -]*level(?: subjects?)?)?",
        text, flags=re.I,
    )
    if cp:
        minimum, prefixes, level = cp.groups()
        total = sum(int(catalog[c]["cp"]) for c in held if c in catalog and catalog[c].get("cp")
                    and (not level or subject_level_from_code(c) == int(level))
                    and (not prefixes or any(c.startswith(prefix) for prefix in prefixes.upper().split("/"))))
        return total >= int(minimum)
    raise PlanGenerationError("A handbook prerequisite needs manual confirmation: " + text + ". Confirm it before generating a verified plan.")


def validate_plan(text: str, state: dict) -> StudyPlan:
    """Use source facts for names/notes, preserve the record, and reject unsafe drafts."""
    if not state.get("meta_confirmed") or state.get("context_conflicts") or not state.get("handbook_valid"):
        raise PlanGenerationError("Confirm the conflicting or missing academic details and load the handbook before planning.")
    draft = parse_plan(text)
    catalog, rules, required, choices = plan_sources(state)
    record = record_for(state)
    if record.unspecified_credit:
        raise PlanGenerationError("This record has unspecified credit. Confirm how that credit satisfies degree requirements before planning.")
    history = {(str(r.year), r.session, r.code): r for r in record.rows}
    if len(history) != len(record.rows):
        raise PlanGenerationError("The record has duplicate attempts in one session. Confirm those rows before planning.")
    grouped = defaultdict(list)
    seen = set()
    future = []
    held = {r.code for r in record.specified_credit if r.code}
    last_record = max((_key(r.year, r.session) for r in record.rows), default=(int(state["meta"]["year"]), -1))
    future_codes = set()
    counted = set(held)
    for year in draft.plan:
        for session in year.sessions:
            position = _key(year.year, session.session)
            for subject in session.subjects:
                key = (year.year, session.session, subject.code)
                if key in seen:
                    raise PlanGenerationError(f"Duplicate plan row for {subject.code}. Regenerate without duplicate attempts.")
                seen.add(key)
                source = catalog.get(subject.code)
                if not source or not source.get("title") or not source.get("cp"):
                    raise PlanGenerationError(f"No authoritative subject data for {subject.code}. Refresh the handbook data.")
                if subject.cp != int(source["cp"]):
                    raise PlanGenerationError(f"Credit points for {subject.code} disagree with the handbook. Regenerate the plan.")
                old = history.get(key)
                if old is not None:
                    if old.nom_cp != subject.cp:
                        raise PlanGenerationError(f"Record credit points for {subject.code} disagree with the handbook. Confirm the transfer credit.")
                    notes = f"{old.status}" + (f"; grade {old.grade}" if old.grade else "")
                    if (old.status == "Complete" and old.grade in PASS_GRADES) or old.status == "Enrolled":
                        counted.add(subject.code)
                else:
                    if position <= last_record:
                        raise PlanGenerationError(f"New subject {subject.code} in {year.year} {session.session} must follow the current enrolment record. Preserve historical/current sessions unchanged.")
                    if subject.code in future_codes or subject.code in {r.code for r in record.rows if r.status == "Enrolled" or (r.status == "Complete" and r.grade in PASS_GRADES)} | held:
                        raise PlanGenerationError(f"{subject.code} is already completed or scheduled. Regenerate without duplicates.")
                    future_codes.add(subject.code)
                    future.append((position, session.session, subject.code))
                    counted.add(subject.code)
                    notes = "Planned"
                grouped[(year.year, session.session)].append(Subject(code=subject.code, name=source["title"], cp=subject.cp, notes=notes))
    missing_history = set(history) - seen
    if missing_history:
        raise PlanGenerationError("The draft omitted or moved enrolment-record subjects. Include every historical/current row unchanged.")
    expanded = expand_held(counted, rules.satisfies)
    if missing := required - expanded:
        raise PlanGenerationError("Required subjects are missing: " + ", ".join(sorted(missing)) + ". Generate all remaining sessions.")
    if rules.core_selection and not rules.core_selection & expanded:
        raise PlanGenerationError("The plan is missing a required core-selection subject.")
    for choice in choices:
        if sum(int(catalog[c]["cp"]) for c in counted & set(choice["codes"])) < choice["cp"]:
            raise PlanGenerationError("The plan is missing the Dean's Scholar component. Include a handbook-listed subject.")
    allowed = required | set(rules.core_selection) | {c for choice in choices for c in choice["codes"]}
    for pool in load_elective_pools(rules.course).get("pools", []):
        allowed.update(resolve_pool_candidates(pool, catalog, set()))
    if future_codes - allowed:
        raise PlanGenerationError("The plan includes subjects outside the course's approved requirements/elective pools.")
    total = sum(int(catalog[c]["cp"]) for c in counted if c in catalog)
    if total != rules.total_cp:
        raise PlanGenerationError(f"Applicable subject credit is {total} CP; the degree requires {rules.total_cp} CP. Resolve excess/transfer credit or generate the remaining sessions.")
    if sum(int(catalog[c]["cp"]) for c in counted if c in catalog and subject_level_from_code(c) == 100) > rules.max_100_level_cp:
        raise PlanGenerationError("The plan exceeds the handbook's 100-level credit limit.")
    # Recorded attempts are authoritative; validate newly proposed placements only.
    for position, session, code in sorted(future):
        prior = held | {r.code for r in record.rows if _key(r.year, r.session) < position and (r.session != "Annual" or r.year < position[0]) and (r.status == "Enrolled" or (r.status == "Complete" and r.grade in PASS_GRADES))}
        prior |= {c for pos, term, c in future if pos < position and (term != "Annual" or pos[0] < position[0])}
        concurrent = prior | {c for pos, _, c in future if pos == position}
        source = catalog[code]
        if source.get("degree_restrictions"):
            raise PlanGenerationError(f"{code} has degree-entry restrictions that need confirmation before scheduling.")
        if not any(o.get("campus", "").casefold() == rules.campus.casefold() and o.get("session", "").casefold() in {session.casefold(), "annual"} for o in source.get("offerings", [])):
            raise PlanGenerationError(f"{code} is not offered at {rules.campus} in {session}. Choose a verified session.")
        for field, available in [("prerequisites", prior), ("corequisites", concurrent)]:
            if not all(requirement_satisfied(expr, available, catalog, rules.satisfies) for expr in source.get(field) or []):
                raise PlanGenerationError(f"{code} has unmet {field}. Move it after the required subjects.")
        if any(normalize_code(c) in expand_held(prior, rules.satisfies) for c in source.get("exclusions", [])):
            raise PlanGenerationError(f"{code} conflicts with a previously completed subject exclusion.")
    years = defaultdict(list)
    for (year, session), subjects in sorted(grouped.items(), key=lambda item: _key(*item[0])):
        years[year].append(Session(session=session, subjects=subjects))
    return StudyPlan(plan=[Year(year=year, sessions=sessions) for year, sessions in years.items()])


def render_plan(plan: StudyPlan) -> str:
    def cell(value):
        return str(value).replace("<", "&lt;").replace(">", "&gt;").replace("|", "&#124;").replace("\n", " ").replace("\r", " ")

    lines = ["**Your suggested study plan:**", "", "| Year | Session | Subject Code | Subject Name | CP | Notes |", "| --- | --- | --- | --- | --- | --- |"]
    for year in plan.plan:
        for session in year.sessions:
            for subject in session.subjects:
                lines.append("| " + " | ".join(cell(v) for v in [year.year, session.session, subject.code, subject.name, subject.cp, subject.notes]) + " |")
    lines += ["", "Confirm enrolment decisions against the official course handbook. Future offerings may change.", "", "```json", json.dumps(plan.model_dump(), ensure_ascii=False, indent=2), "```"]
    return "\n".join(lines)
