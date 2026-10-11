"""Student records under tests/e2e/cases, read the way the app reads a SOLS paste."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.services.enrolment import EnrolmentRecord, parse_enrolment

CASES_DIR = Path(__file__).parent / "cases"
SESSION_ORDER = {"Autumn": 0, "Annual": 0, "Spring": 1}
_MAJOR_LINE = re.compile(r"^\*\*Major(?: \d+)?:\*\*[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)


def session_key(year: int, session: str) -> tuple[int, int]:
    return (year, SESSION_ORDER[session])


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    record: EnrolmentRecord
    # Read from the header, not from the parser: that is what the student confirms in chat.
    majors: list[str]

    @property
    def campus(self) -> str:
        return self.record.campus or "Wollongong"

    @property
    def commencement_year(self) -> int:
        return min(row.year for row in self.record.rows)

    @property
    def last_key(self) -> tuple[int, int]:
        return max(session_key(row.year, row.session) for row in self.record.rows)


def load_case(path: Path) -> Case:
    text = path.read_text()
    return Case(path.stem, text, parse_enrolment(text), _MAJOR_LINE.findall(text))


def load_cases() -> list[Case]:
    return [load_case(path) for path in sorted(CASES_DIR.glob("*.md"))]
