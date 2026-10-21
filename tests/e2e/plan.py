"""Read the structured plan the planner appends to its reply."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_FENCE = re.compile(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", re.IGNORECASE)


@dataclass(frozen=True)
class PlannedSubject:
    year: int
    session: str
    code: str
    name: str
    cp: int
    notes: str


def parse_plan(text: str) -> list[PlannedSubject] | None:
    """Subjects from the last JSON block of the reply, or None if there is no valid plan."""
    blocks = _FENCE.findall(text or "")
    if not blocks:
        return None
    try:
        years = json.loads(blocks[-1])["plan"]
        return [
            PlannedSubject(
                year=int(year["year"]),
                session=str(session["session"]).strip().title(),
                code=str(subject["code"]).upper().replace(" ", ""),
                name=str(subject.get("name") or ""),
                cp=int(subject["cp"]),
                notes=str(subject.get("notes") or ""),
            )
            for year in years
            for session in year["sessions"]
            for subject in session["subjects"]
        ]
    except (KeyError, TypeError, ValueError):
        return None
