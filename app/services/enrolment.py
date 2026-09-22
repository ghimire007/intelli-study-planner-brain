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

Two paste shapes are read. One still has its markdown tables; the other has
lost them, because copying out of SOLS through a plain-text field can collapse
the whole record into a single run of words. The allowlist and the shape checks
are the same either way — see parse_enrolment.
"""
from __future__ import annotations

import re
from itertools import pairwise

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

# Teaching sessions. The table parser does not need these — there the session
# is a delimited cell — but a paste that has lost its table markup has no
# column boundaries left, so the session is one of the tokens that pins down
# where a row starts (see _parse_flat).
KNOWN_SESSIONS = frozenset({"Annual", "Autumn", "Spring", "Summer", "Winter"})


def _alternation(values: frozenset[str]) -> str:
    """Regex alternation over a known set, longest first.

    Backtracking would reach "PS" over "P" either way; ordering it here means
    the pattern does not quietly depend on that.
    """
    return "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True))


_COURSE = re.compile(r"^\*{0,2}Course:?\*{0,2}\s*(\d{3,4})\b", re.IGNORECASE)
_CAMPUS = re.compile(r"^\*{0,2}Campus:?\*{0,2}\s*([A-Za-z][A-Za-z ]*?)\s*(?:\||$)", re.IGNORECASE)
_MAJOR = re.compile(r"^\*{0,2}(?:(Second)\s+)?Major(?:\s+\d+)?:?\*{0,2}\s*(.+?)\s*$", re.IGNORECASE)
# "AIBD — Artificial Intelligence and Big Data" -> "AIBD"; a major is a short
# uppercase code, so "Not yet declared" simply yields nothing.
_MAJOR_CODE = re.compile(r"^([A-Z]{2,6})\b")
# Some records name the major without its code ("Network Design and
# Management"). The title is worth keeping — lookup_major recovers the code
# from it — but it is shape-checked like every other field, and "Not yet
# declared" is not a major.
_MAJOR_TITLE = re.compile(r"^[A-Z][A-Za-z]*(?: [A-Za-z&-]+){1,7}$")
_UNDECLARED = re.compile(r"^(?:not yet declared|undeclared|none|n/?a|tbd)$", re.IGNORECASE)

# One row of a paste that arrived as a single run of text, its table markup and
# with it its column boundaries gone. Mark and grade are absent rather than
# blank on an unfinished subject, so everything after the nominal CP is
# optional and the row is pinned instead by the tokens we know: a teaching
# session, a subject code, a status. Campus excludes digits so it cannot
# swallow a number, and the whole shape must match end to end.
_FLAT_ROW = re.compile(
    r"(?P<year>(?:19|20)\d{2})\s+"
    rf"(?P<session>{_alternation(KNOWN_SESSIONS)})\s+"
    r"(?P<campus>[A-Za-z][A-Za-z/ ]*?)\s+"
    r"(?P<code>[A-Z]{2,4}\d{3}[A-Z]?)\s+"
    r"(?P<nom_cp>\d{1,2})"
    r"(?:\s+(?P<mark>\d{1,3}))?"
    rf"(?:\s+(?P<grade>{_alternation(KNOWN_GRADES)}))?"
    # The status must not stop inside a longer word: without this, "Completed"
    # reads as "Complete" with a stray "d" left behind. The grade needs no such
    # guard — the whitespace before the status already forces it to give back a
    # partial word.
    rf"\s+(?P<status>{_alternation(KNOWN_STATUSES)})(?![A-Za-z])"
)

# A credit section in flat text, up to the next heading. Its body is scanned
# only for evidence that it holds rows rather than the word "None".
_FLAT_CREDIT = re.compile(r"\b(?:Unspecified|Specified)\s+Credit\b(?P<body>[^#]*)", re.IGNORECASE)

# The header labels SOLS prints. In flat text one of these is what tells us the
# previous value has ended — "Major: Network Design and Management Honours GPA:
# 3.8" has no other boundary between the major and the next label. Matching a
# known set rather than any capitalised word matters in both directions: a
# generic "Word:" terminator stops one word too late and carries "Honours" into
# the major, while a label we do not know leaves the value with no reachable
# terminator, so the field is dropped instead of over-captured.
_FLAT_LABELS = frozenset(
    {
        "Student", "Effective Date", "Course", "Instance", "Campus", "Delivery",
        "Status", "Second Major", "Major", "Note", "Notes", "Supervisor",
        "Honours GPA", "GPA", "WAM",
    }
)

# A header value runs until the next label, until the column headings, or until
# the first row.
_FLAT_END = (
    rf"(?=\s+(?:(?:{_alternation(_FLAT_LABELS)})\s*:|Year\s+Session\b|(?:19|20)\d{{2}}\s)|\s*$)"
)
_FLAT_COURSE = re.compile(r"\bCourse\s*:\s*(\d{3,4})\b", re.IGNORECASE)
_FLAT_CAMPUS = re.compile(
    rf"\bCampus\s*:\s*(?P<value>[A-Za-z][A-Za-z ]{{0,40}}?){_FLAT_END}", re.IGNORECASE
)
_FLAT_MAJOR = re.compile(
    rf"\b(?:Second\s+)?Major\s*:\s*(?P<value>[A-Za-z][A-Za-z0-9 &—-]{{0,60}}?){_FLAT_END}",
    re.IGNORECASE,
)


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
    name = re.sub(r"\s+", " ", cell.replace("*", "").strip()).lower()
    return "nom cp" if name in {"nomcp", "nominal cp"} else name


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


def _add_major(header: dict, value: str) -> None:
    """Record a major by its code when it has one, else by its plain title."""
    if code := _MAJOR_CODE.match(value):
        header["majors"].append(code.group(1))
    elif _MAJOR_TITLE.match(value) and not _UNDECLARED.match(value):
        header["majors"].append(value)


def _read_header_line(line: str, header: dict) -> None:
    """Pick the three allowlisted header fields out of a non-table line."""
    if (course := _COURSE.match(line)) and header["course_code"] is None:
        header["course_code"] = course.group(1)
        return
    if (campus := _CAMPUS.match(line)) and header["campus"] is None:
        header["campus"] = campus.group(1).strip()
        return
    if major := _MAJOR.match(line):
        _add_major(header, major.group(2).strip())


_NO_HISTORY = (
    "No enrolment history was found. Paste the enrolment record from SOLS, "
    "including the table of subjects."
)


def parse_enrolment(raw_sols: str) -> EnrolmentRecord:
    """Parse a SOLS paste into its allowlisted fields.

    Copying the record out of SOLS does not always preserve the table: pasted
    through a plain-text field it can arrive as one unbroken run of words. Both
    shapes are read, by the same allowlist and the same shape checks.

    Raises UnreadableRecord if the paste has no readable enrolment history, or
    if any value in one fails its shape check.
    """
    # A real markdown table spans at least a heading row and a row of its own;
    # a single line of pipes is a table that lost its line breaks, so it goes
    # down the relaxed path with everything else that arrived run together.
    if sum(line.lstrip().startswith("|") for line in raw_sols.splitlines()) > 1:
        return _parse_table(raw_sols)
    return _parse_flat(raw_sols)


def _parse_flat(raw_sols: str) -> EnrolmentRecord:
    """Parse a paste whose table markup did not survive the copy.

    With no columns left, rows are recovered by matching the known row shape
    end to end. Text left over between two rows means a row was only partly
    understood, and that is a refusal rather than a silent drop: a record
    quietly missing a subject is worse than no record at all.
    """
    # Pipes and bold markers may or may not have survived the copy; neither
    # carries any allowlisted meaning, so both become whitespace and the one
    # shape below covers a run-together markdown table, a tab-separated copy
    # straight out of the browser, and plain text alike.
    text = " ".join(raw_sols.replace("|", " ").replace("*", " ").split())

    matches = list(_FLAT_ROW.finditer(text))
    if not matches:
        if re.search(r"\b[A-Z]{2,4}\d{3}[A-Z]?\b", text):
            raise UnreadableRecord(
                "Subject codes were found but no row could be read in full. Each row needs "
                "its year, session, campus, subject code, nominal CP and status."
            )
        raise UnreadableRecord(_NO_HISTORY)

    for previous, current in pairwise(matches):
        if leftover := text[previous.end() : current.start()].strip():
            raise UnreadableRecord(f"Could not read the subject row at {leftover!r}.")

    # Advanced standing cannot be read here: a specified-credit row carries a
    # free-text subject name, and with the columns gone there is nothing to
    # tell where that name ends. A section reading "None" costs nothing, but
    # dropping real credit rows would understate the credit the student holds,
    # so those are a refusal.
    tail = text[matches[-1].end() :]
    if any(re.search(r"\d", section.group("body")) for section in _FLAT_CREDIT.finditer(tail)):
        raise UnreadableRecord(
            "This record lists advanced standing, which cannot be read once the table "
            "layout is lost. Paste the record again with each row on its own line."
        )

    header: dict = {"course_code": None, "campus": None, "majors": []}
    preamble = text[: matches[0].start()]
    if course := _FLAT_COURSE.search(preamble):
        header["course_code"] = course.group(1)
    if campus := _FLAT_CAMPUS.search(preamble):
        header["campus"] = campus.group("value").strip()
    for major in _FLAT_MAJOR.finditer(preamble):
        _add_major(header, major.group("value").strip())

    return EnrolmentRecord(
        course_code=header["course_code"],
        campus=header["campus"],
        majors=header["majors"],
        # The mark is captured only so the row shape stays anchored; like the
        # table parser, this never reads it out.
        rows=[
            EnrolmentRow(
                year=int(row.group("year")),
                session=row.group("session"),
                campus=row.group("campus").split("/")[0].strip(),
                code=row.group("code"),
                nom_cp=int(row.group("nom_cp")),
                grade=row.group("grade"),
                status=row.group("status"),
            )
            for row in matches
        ],
        specified_credit=[],
        unspecified_credit=[],
    )


def _parse_table(raw_sols: str) -> EnrolmentRecord:
    """Parse a paste that still has its markdown tables."""
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
        raise UnreadableRecord(_NO_HISTORY)

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
