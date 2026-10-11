"""The student-facing plan message, assembled from validated data.

The model only ever returns the plan as JSON. Everything the student reads
around it (progress summary, audit result, table, credit summary, disclaimer)
is built here from the validated plan, the enrolment record and the handbook
data, so none of it can disagree with what was checked.
"""
from __future__ import annotations

import html
import json

from app.services.course_catalog import COURSE_TITLES
from app.services.eligibility_service import resolve_major_code
from app.services.enrolment import UnreadableRecord
from app.services.study_plan import (
    PASS_GRADES,
    PlanGenerationError,
    StudyPlan,
    merge_record_history,
    parse_plan,
    plan_sources,
    record_for,
    validate_plan,
)

_FAILED_GRADES = frozenset({"F", "TF"})

_VERIFIED_CHECKS = (
    "Every enrolment-record subject is kept exactly as recorded",
    "Subject names and credit points match the handbook",
    "All required subjects are scheduled (core, major, core selection and Dean's Scholar component where they apply)",
    "Planned subjects come from the course's approved requirements and elective pools",
    "Total applicable credit equals the degree requirement",
    "The 100-level credit limit is respected",
    "Planned subjects are offered at your campus in their session, with prerequisites, corequisites and exclusions satisfied",
)

CORRECTION_HINT = (
    "To save tokens, ask Courseo to correct this plan (for example, “please fix the issue above”) "
    "rather than starting again."
)


def _text(value) -> str:
    """Free text that may come from the model or an error message: never raw HTML."""
    return html.escape(str(value), quote=False)


def _json_text(plan: StudyPlan) -> str:
    """The plan as JSON with HTML metacharacters written as JSON escapes, so a renderer
    never sees a tag in it while a JSON parser reads exactly the same values."""
    text = json.dumps(plan.model_dump(), ensure_ascii=False, indent=2)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _cell(value) -> str:
    return html.escape(str(value), quote=False).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")


def _majors(meta: dict) -> list[str]:
    majors = meta.get("majors")
    if majors is None:
        majors = [meta.get("major")] if meta.get("major") else []
    if isinstance(majors, str):
        majors = [majors]
    return [str(m) for m in majors if m]


def _category_lookup(state: dict, rules, choices: list[dict]):
    core = set(rules.core_subjects) | {rules.capstone_code} | set(rules.core_selection)
    major_codes: set[str] = set()
    for major in _majors(state.get("meta") or {}):
        code = resolve_major_code(major, rules)
        if code is not None:
            major_codes |= set(rules.major_core.get(code, ()))
    scholar = {c for choice in choices for c in choice["codes"]}

    def category(code: str) -> str:
        if code in core:
            return "Core"
        if code in major_codes:
            return "Major"
        if code in scholar:
            return "Dean's Scholar"
        return "Elective"

    return category


def _offered_sessions(entry: dict, campus: str) -> str:
    sessions = sorted({
        o.get("session", "") for o in entry.get("offerings", [])
        if o.get("campus", "").casefold() == campus.casefold() and o.get("session")
    })
    return ", ".join(sessions) or "—"


def _requirements(entry: dict, field: str) -> str:
    return "; ".join(str(x) for x in entry.get(field) or []) or "None"


def _preamble(state: dict, record, plan: StudyPlan, rules, verified: bool) -> str:
    meta = state.get("meta") or {}
    code = meta.get("degree_code")
    title = COURSE_TITLES.get(code)
    course = f"{title} ({code})" if title else str(code or "your course")
    majors = ", ".join(_majors(meta)) or "No major"
    lines = [f"**Course:** {course} — {rules.campus}", f"**Major:** {majors}"]

    if verified:
        completed = sum(r.nom_cp for r in record.rows if r.status == "Complete" and r.grade in PASS_GRADES)
        completed += sum(c.nom_cp for c in record.specified_credit if c.code)
        enrolled = sum(r.nom_cp for r in record.rows if r.status == "Enrolled")
        remaining = sum(s.cp for y in plan.plan for t in y.sessions for s in t.subjects if s.notes == "Planned")
        lines.append(
            f"You have {completed} CP completed or credited and {enrolled} CP currently enrolled; "
            f"{remaining} CP remain to be scheduled towards the {rules.total_cp} CP degree."
        )
    failed = sorted({f"{r.code} ({r.grade})" for r in record.rows if r.grade in _FAILED_GRADES})
    if failed:
        lines.append("**Failed or repeated subjects:** " + ", ".join(failed))
    return "\n\n".join(lines)


def _audit(verified: bool, issue: str | None) -> str:
    body = ["<details>", "<summary>Audit & Rule Verification (click to expand)</summary>", ""]
    if verified:
        body += [f"- ✅ {check}" for check in _VERIFIED_CHECKS]
        body += ["", "**Final Status: PASS** — No issues found."]
    else:
        body += ["**Final Status: FAIL** — this plan did not pass every check.", "", f"- ❌ {_text(issue)}"]
    body += ["", "</details>"]
    return "\n".join(body)


def _table(state: dict, record, plan: StudyPlan, catalog: dict, rules, choices: list[dict]) -> str:
    category = _category_lookup(state, rules, choices)
    failed_attempts = {(str(r.year), r.session, r.code): r.grade for r in record.rows if r.grade in _FAILED_GRADES}
    failed_codes = {code for _, _, code in failed_attempts}
    repeated: set[str] = set()

    lines = [
        "**Your suggested study plan:**", "",
        "| Year | Session | Subject Code | Subject Name | CP | Category | Valid sessions | Prerequisites | Corequisites | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for year in plan.plan:
        for session in year.sessions:
            for subject in session.subjects:
                entry = catalog.get(subject.code) or {}
                label, name = subject.code, subject.name
                grade = failed_attempts.get((year.year, session.session, subject.code))
                if grade:
                    label, name = f"{label} ({grade})", f"{name} ({grade})"
                elif subject.notes == "Planned" and subject.code in failed_codes and subject.code not in repeated:
                    repeated.add(subject.code)
                    label, name = f"{label} (repeat)", f"{name} (repeat)"
                url = entry.get("url")
                safe_link = isinstance(url, str) and url.startswith("https://")
                code_cell = f'<a href="{html.escape(url)}" target="_blank" rel="noopener noreferrer">{_cell(label)}</a>' if safe_link else _cell(label)
                lines.append("| " + " | ".join([
                    _cell(year.year), _cell(session.session), code_cell, _cell(name), _cell(subject.cp),
                    category(subject.code) if entry else "—",
                    _cell(_offered_sessions(entry, rules.campus)),
                    _cell(_requirements(entry, "prerequisites")), _cell(_requirements(entry, "corequisites")),
                    _cell(subject.notes),
                ]) + " |")
    return "\n".join(lines)


def _credit_summary(record, plan: StudyPlan, rules) -> str:
    completed = sum(r.nom_cp for r in record.rows if r.status == "Complete" and r.grade in PASS_GRADES)
    credited = sum(c.nom_cp for c in record.specified_credit if c.code)
    enrolled = sum(r.nom_cp for r in record.rows if r.status == "Enrolled")
    not_awarded = sum(r.nom_cp for r in record.rows if r.grade in _FAILED_GRADES)
    remaining = sum(s.cp for y in plan.plan for t in y.sessions for s in t.subjects if s.notes == "Planned")
    return "\n".join([
        "**Credit Point Summary:**",
        f"- Overall completed CP: {completed + credited} CP",
        f"- Completed / Credit awarded: {completed} CP completed + {credited} CP credit awarded",
        f"- Excess / Non-awarded: {not_awarded} CP (failed attempts, not counted)",
        f"- Currently enrolled: {enrolled} CP",
        f"- Remaining in plan: {remaining} CP",
        f"- **Total applicable: {rules.total_cp} CP**",
    ])


def _disclaimer(state: dict) -> str:
    code = (state.get("meta") or {}).get("degree_code")
    link = f"https://courses.uow.edu.au/courses/2026/{code}" if code else "https://courses.uow.edu.au"
    return (
        "*Disclaimer: This study plan is a suggested guide based on current handbook rules and your SOLS record. "
        f'Double-check all requirements against the official <a href="{html.escape(link)}" target="_blank" rel="noopener noreferrer">UOW Course Handbook</a>.*'
    )


def build_plan_message(plan: StudyPlan, state: dict, *, issue: str | None = None) -> str:
    """The full message. `issue` set means the plan did not pass validation: it is
    still shown, marked FAIL, with the problem and how to fix it at the end."""
    catalog, rules, _, choices = plan_sources(state)
    record = record_for(state)
    verified = issue is None

    parts = [
        _preamble(state, record, plan, rules, verified),
        _audit(verified, issue),
        _table(state, record, plan, catalog, rules, choices),
    ]
    if verified:
        parts.append(_credit_summary(record, plan, rules))
    parts.append(_disclaimer(state))
    # The one JSON block parse_plan reads back, so the message is its own source of truth.
    parts.append("```json\n" + _json_text(plan) + "\n```")
    if issue:
        parts.append(f"---\n\n**Plan validation warning:** {_text(issue)}\n\n{CORRECTION_HINT}")
    return "\n\n".join(parts)


def render_plan_message(plan_text: str, state: dict, issue: str | None = None) -> tuple[str, str]:
    """(message to show, plan to store) for whatever the model produced. Never raises:
    a plan that cannot be verified is still shown, marked as such, with the reason."""
    try:
        # Even a recovered checkpoint is re-checked: a formatted draft is not proof of validity.
        validated = validate_plan(plan_text, state)
        return build_plan_message(validated, state, issue=issue), validated.model_dump_json()
    except (PlanGenerationError, UnreadableRecord) as exc:
        problem = issue or str(exc)

    try:
        try:
            draft = parse_plan(merge_record_history(plan_text, state))
        except PlanGenerationError:
            draft = parse_plan(plan_text)
        return build_plan_message(draft, state, issue=problem), plan_text
    except (PlanGenerationError, UnreadableRecord):
        return f"{_text(plan_text)}\n\n---\n\n**Plan validation warning:** {_text(problem)}\n\n{CORRECTION_HINT}", plan_text

