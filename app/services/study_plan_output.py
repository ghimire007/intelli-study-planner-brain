"""Validate the plan payload consumed by the Study Plan panel and PDF exporter."""
from __future__ import annotations

import json
import re

from app.schemas.study_plan import StudyPlanContent

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)```", re.IGNORECASE)
_PLAN_TABLE = re.compile(
    r"^\s*\|[^\n]*\bYear\b[^\n]*\bSession\b[^\n]*\bSubject Code\b",
    re.IGNORECASE | re.MULTILINE,
)


def read_study_plan(text: str) -> tuple[StudyPlanContent, str]:
    """Return the final plan and its source block; never infer subjects from prose."""
    candidates = [(match.group(1), match.group(0)) for match in _FENCE.finditer(text)]
    candidates.append((text.strip(), text.strip()))
    for raw, block in reversed(candidates):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(data, dict) or "plan" not in data:
            continue
        plan = StudyPlanContent.model_validate(data)
        if not any(session.subjects for year in plan.plan for session in year.sessions):
            raise ValueError("The study plan must contain subject rows.")
        return plan, block
    raise ValueError("The study plan is missing a valid JSON plan payload.")


def study_plan_table(plan: StudyPlanContent) -> str:
    """Render the same subjects the frontend uses for its cards and PDF."""
    def cell(value: str) -> str:
        return re.sub(r"[\r\n]+", " ", value).replace("|", "&#124;")

    lines = [
        "| Year | Session | Subject Code | Subject Name | CP | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for year in plan.plan:
        for session in year.sessions:
            for subject in session.subjects:
                values = [year.year, session.session, subject.code, subject.name,
                          f"{subject.cp:g}", subject.notes or ""]
                lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    return "\n".join(lines)


def normalize_study_plan_output(text: str) -> str:
    """Guarantee a visible table and a final JSON fence for the existing UI."""
    plan, block = read_study_plan(text)
    prose = text.replace(block, "").strip()
    if not _PLAN_TABLE.search(prose):
        prose = f"{prose}\n\n**Your suggested study plan:**\n\n{study_plan_table(plan)}".strip()
    payload = json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, allow_nan=False)
    return f"{prose}\n\n```json\n{payload}\n```"
