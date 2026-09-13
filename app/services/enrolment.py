"""Project a raw SOLS enrolment paste onto the fields the advisor may see.

An allowlist, not a blocklist. The paste is parsed into a typed record and a
fresh text block is rendered from that record, so a field nobody anticipated is
never carried anywhere rather than being redacted on the way past. Compare
`app/services/pii.py`, which scrubs free-form chat turns by pattern and is the
weaker tool — use this one for anything that comes out of SOLS.

What survives: year, session, campus, subject code, nominal CP, grade and
status per row, plus course code, campus and major(s) from the header, plus the
credit tables. What does not: the student's name and number, the numeric mark,
subject names, effective dates, supervisors, GPAs, free-text notes, delivery
mode, supplementary qualifications, and anything else at all.

Values are shape-checked as they are parsed, so no column can carry arbitrary
text into the prompt. A paste we cannot read raises UnreadableRecord rather
than falling back to the raw text: an unparseable record is exactly the one
most likely to hold something unexpected.
"""
from __future__ import annotations

import re

from pydantic import BaseModel

# Subject codes are 2-4 letters, three digits, and occasionally a suffix
# letter (CSIT110, MATH255, CSIT901).
_SUBJECT_CODE = re.compile(r"^[A-Z]{2,4}\d{3}[A-Z]?$")

# The official UOW grade table. A value outside it means the paste is malformed
# or its columns are misaligned, not that a new grade exists — adding one here
# is a deliberate one-line change.
KNOWN_GRADES = frozenset(
    {
        "HD", "D", "C", "P", "PS",   # passed
        "F", "TF", "U",              # failed
        "CO", "S", "E",              # ungraded pass / Graduate Medicine
        "IPC", "IPR",                # in progress
        "WH", "WD", "WS", "ND",      # result withheld or not declared
    }
)

# Statuses observed across the enrolment records we support. Same reasoning as
# the grades above: an unrecognised status rejects the record.
KNOWN_STATUSES = frozenset(
    {
        "Complete",
        "Enrolled",
        "Withdrawn",
        "Leave of Absence",
        "Not Counted (Prior Course)",
    }
)

_COURSE = re.compile(r"^\*{0,2}Course:?\*{0,2}\s*(\d{3,4})\b", re.IGNORECASE)
_CAMPUS = re.compile(r"^\*{0,2}Campus:?\*{0,2}\s*([A-Za-z][A-Za-z ]*?)\s*(?:\||$)", re.IGNORECASE)
_MAJOR = re.compile(r"^\*{0,2}(?:(Second)\s+)?Major:?\*{0,2}\s*(.+?)\s*$", re.IGNORECASE)
# "AIBD — Artificial Intelligence and Big Data" -> "AIBD"; a major is a short
# uppercase code, so "Not yet declared" simply yields nothing.
_MAJOR_CODE = re.compile(r"^([A-Z]{2,6})\b")


class UnreadableRecord(ValueError):
    """The paste could not be projected, so nothing may be sent onward.

    Subclasses ValueError so the chat API turns it into a 422 with this
    message, the same way it handles other unprocessable input.
    """


class EnrolmentRow(BaseModel):
    """One subject attempt. No mark, no subject name."""

    year: int
    session: str
    campus: str
    code: str
    nom_cp: int
    grade: str | None
    status: str


class CreditRow(BaseModel):
    """One advanced-standing row — specified (a named subject) or not."""

    course: str
    code: str | None
    level: str | None
    nom_cp: int


class EnrolmentRecord(BaseModel):
    """Everything the advisor is allowed to know about a student's enrolment."""

    course_code: str | None
    campus: str | None
    majors: list[str]
    rows: list[EnrolmentRow]
    specified_credit: list[CreditRow]
    unspecified_credit: list[CreditRow]


def _norm(cell: str) -> str:
    """Normalise a header cell for matching: lowercase, unbolded, despaced."""
    return re.sub(r"\s+", " ", cell.replace("*", "").strip()).lower()


def _split_row(line: str) -> list[str]:
    """Split a markdown table row into its cells, dropping the outer pipes."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_separator(cells: list[str]) -> bool:
    return all(set(cell) <= {"-", ":", " "} and cell for cell in cells)


def _classify(headers: list[str]) -> str | None:
    """Name the table this header row introduces, or None if it is not one."""
    seen = set(headers)
    if {"year", "subject code", "status"} <= seen:
        return "enrolment"
    if {"course", "subject code", "nom cp"} <= seen:
        return "specified"
    if {"course", "level", "nom cp"} <= seen:
        return "unspecified"
    # Any other table — supplementary qualifications, say — is not on the
    # allowlist, so its rows are skipped rather than parsed.
    return None


def _require_int(value: str, field: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise UnreadableRecord(f"Could not read {field} from {value!r}.") from exc


def _enrolment_row(cells: dict[str, str]) -> EnrolmentRow:
    code = cells.get("subject code", "").upper()
    if not _SUBJECT_CODE.match(code):
        raise UnreadableRecord(f"{code!r} is not a subject code.")

    grade = cells.get("grade", "").upper() or None
    if grade is not None and grade not in KNOWN_GRADES:
        raise UnreadableRecord(f"{grade!r} is not a known grade.")

    status = cells.get("status", "")
    if status not in KNOWN_STATUSES:
        raise UnreadableRecord(f"{status!r} is not a known enrolment status.")

    # The column is "Campus/Delivery"; only the campus half is on the allowlist.
    campus = cells.get("campus/delivery") or cells.get("campus", "")

    return EnrolmentRow(
        year=_require_int(cells.get("year", ""), "year"),
        session=cells.get("session", ""),
        campus=campus.split("/")[0].strip(),
        code=code,
        nom_cp=_require_int(cells.get("nom cp", ""), "nominal CP"),
        grade=grade,
        status=status,
    )


def _credit_row(cells: dict[str, str]) -> CreditRow:
    code = cells.get("subject code", "").upper() or None
    if code is not None and not _SUBJECT_CODE.match(code):
        raise UnreadableRecord(f"{code!r} is not a subject code.")
    return CreditRow(
        course=cells.get("course", ""),
        code=code,
        level=cells.get("level") or None,
        nom_cp=_require_int(cells.get("nom cp", ""), "nominal CP"),
    )


def _read_header_line(line: str, header: dict) -> None:
    """Pick the three allowlisted header fields out of a non-table line."""
    if (course := _COURSE.match(line)) and header["course_code"] is None:
        header["course_code"] = course.group(1)
        return
    if (campus := _CAMPUS.match(line)) and header["campus"] is None:
        header["campus"] = campus.group(1).strip()
        return
    if major := _MAJOR.match(line):
        if code := _MAJOR_CODE.match(major.group(2).strip()):
            header["majors"].append(code.group(1))


def parse_enrolment(raw_sols: str) -> EnrolmentRecord:
    """Parse a SOLS paste into its allowlisted fields.

    Raises UnreadableRecord if the paste has no readable enrolment table, or if
    any value in one fails its shape check.
    """
    header: dict = {"course_code": None, "campus": None, "majors": []}
    rows: list[EnrolmentRow] = []
    specified: list[CreditRow] = []
    unspecified: list[CreditRow] = []

    table: str | None = None
    columns: list[str] = []

    for raw_line in raw_sols.splitlines():
        line = raw_line.strip()

        if not line.startswith("|"):
            table, columns = None, []  # a non-table line closes the table
            _read_header_line(line, header)
            continue

        cells = _split_row(line)
        if _is_separator(cells):
            continue

        if (kind := _classify([_norm(cell) for cell in cells])) is not None:
            table, columns = kind, [_norm(cell) for cell in cells]
            continue

        if table is None:
            continue  # a table we do not recognise; its rows stay behind

        if len(cells) != len(columns):
            raise UnreadableRecord(
                f"Row has {len(cells)} columns but the table header has {len(columns)}."
            )

        by_name = dict(zip(columns, cells, strict=True))
        if table == "enrolment":
            rows.append(_enrolment_row(by_name))
        elif table == "specified":
            specified.append(_credit_row(by_name))
        else:
            unspecified.append(_credit_row(by_name))

    if not rows:
        raise UnreadableRecord(
            "No enrolment history was found. Paste the enrolment record from SOLS, "
            "including the table of subjects."
        )

    return EnrolmentRecord(
        course_code=header["course_code"],
        campus=header["campus"],
        majors=header["majors"],
        rows=rows,
        specified_credit=specified,
        unspecified_credit=unspecified,
    )


def _table(headings: list[str], rows: list[list[str]]) -> list[str]:
    divider = ["|" + "|".join("---" for _ in headings) + "|"]
    body = ["| " + " | ".join(cells) + " |" for cells in rows]
    return ["| " + " | ".join(headings) + " |", *divider, *body]


def render_for_llm(record: EnrolmentRecord) -> str:
    """Render the record back to text for the prompt.

    Column names match the ones the system prompt already refers to ("Nom CP",
    "Grade", "Status"), so the projection needs no prompt changes.
    """
    lines = ["# Enrolment Record", ""]
    if record.course_code:
        lines.append(f"**Course:** {record.course_code}")
    if record.campus:
        lines.append(f"**Campus:** {record.campus}")
    for index, major in enumerate(record.majors):
        lines.append(f"**Major{f' {index + 1}' if index else ''}:** {major}")

    lines += ["", "## Enrolment History", ""]
    lines += _table(
        ["Year", "Session", "Campus", "Subject Code", "Nom CP", "Grade", "Status"],
        [
            [str(row.year), row.session, row.campus, row.code, str(row.nom_cp),
             row.grade or "", row.status]
            for row in record.rows
        ],
    )

    if record.specified_credit:
        lines += ["", "## Specified Credit", ""]
        lines += _table(
            ["Course", "Subject Code", "Nom CP"],
            [[row.course, row.code or "", str(row.nom_cp)] for row in record.specified_credit],
        )

    if record.unspecified_credit:
        lines += ["", "## Unspecified Credit", ""]
        lines += _table(
            ["Course", "Level", "Nom CP"],
            [[row.course, row.level or "", str(row.nom_cp)] for row in record.unspecified_credit],
        )

    return "\n".join(lines)


def project(raw_sols: str) -> str:
    """Parse a SOLS paste and render only its allowlisted fields."""
    return render_for_llm(parse_enrolment(raw_sols))
