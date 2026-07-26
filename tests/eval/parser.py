"""
Convert .md(study plan outpt and enrollment record) to python objects


Public surface
--------------
Output (LLM study plan) side:
- ScheduledSubject, AuditResult, StudyPlan : dataclasses.
- SUBJECT_CODE_PATTERN                     : check subject code pattern is [A-Z]{4}\d{3}
- extract_subject_codes(text)              : str -> set[str].
- parse_study_plan_table(text)             : str -> list[ScheduledSubject].
- parse_reply(text)                        : full reply -> StudyPlan (stub).

Input (student SOLS) side:
- EnrolmentRow, SpecifiedCredit, UnspecifiedCredit : dataclasses.
- PASSING_GRADES                            : frozenset of completion grades.
- parse_sols_enrolment(text)                : str -> list[EnrolmentRow].
- parse_specified_credits(text)             : str -> list[SpecifiedCredit].
- parse_unspecified_credits(text)           : str -> list[UnspecifiedCredit].
- is_complete(row)                          : EnrolmentRow -> bool.
- completed_subject_codes(rows)             : list[EnrolmentRow] -> set[str].
- completed_cp_from_history(rows)           : list[EnrolmentRow] -> int.
- all_completed_subject_codes(sols_md)      : str -> set[str] (history + specified).
- total_completed_cp(sols_md)               : str -> int (history + specified + unspecified).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


# ===========================================================================
# Dataclasses — output (study plan)
# ===========================================================================

@dataclass
class ScheduledSubject:
    """
    One row of the **Study Plan:** markdown table.

    The four fields `year`, `session`, `subject_code`, `credit_points` adhere
    to the Phase 2.2 schema. `name` and `notes` are kept verbatim from the
    table for richer reporting and may be ignored by validators.
    """
    year: int
    session: str           # spec restricts to "Autumn"|"Spring"; parser stays permissive
    subject_code: str      # validated against SUBJECT_CODE_PATTERN
    credit_points: int     # typically 6, 12 for CSIT321 (summed across both parts)
    name: str = ""
    notes: str = ""


@dataclass
class AuditResult:
    """Parsed **Audit:** block from the assistant reply. Later-phase."""
    core: list[str] = field(default_factory=list)
    core_selection: str | None = None
    major_core: dict[str, list[str]] = field(default_factory=dict)
    electives: list[str] = field(default_factory=list)
    unspecified_cp: int = 0
    total_cp: int = 0


@dataclass
class StudyPlan:
    """Full parsed reply: audit + scheduled rows + CP totals. Later-phase."""
    audit: AuditResult
    scheduled: list[ScheduledSubject]
    completed_cp: int
    planned_cp: int
    total_cp: int


# ===========================================================================
# Dataclasses — input (SOLS record)
# ===========================================================================

@dataclass
class EnrolmentRow:
    """
    One row of the SOLS Enrolment History table.

    Test records use the 8-column layout
    `| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |`.
    `mark` and `grade` are `None` when the cell is blank (e.g. Enrolled or
    Withdrawn rows have no mark yet).
    """
    year: int
    session: str               # "Autumn" | "Spring" | "Annual"
    campus_delivery: str
    subject_code: str
    nom_cp: int
    mark: int | None
    grade: str | None
    status: str                # "Complete" | "Enrolled" | "Withdrawn" | "Leave of Absence" | "Not Counted (Prior Course)" | ...


@dataclass
class SpecifiedCredit:
    """One row of the SOLS Specified Credit table (transfer credit with a specific subject code)."""
    course: str
    subject_code: str
    name: str
    level: int
    nom_cp: int


@dataclass
class UnspecifiedCredit:
    """One row of the SOLS Unspecified Credit table (transfer credit with no specific subject code)."""
    course: str
    level: int
    nom_cp: int


# ===========================================================================
# Subject Extractor
# ===========================================================================

# UOW subject codes are 4 uppercase letters followed by 3 digits:
#   CSIT110, CSCI235, MATH255, ISIT312, ENGG100, CSIT321, ECTE250, CSCI291, ...
# Word boundaries (`\b`) are a strict superset of the spec pattern
# `r'[A-Z]{4}\d{3}'` — they prevent accidental matches inside longer
# alphanumeric tokens (e.g. `XCSIT1100`) without rejecting any valid code.
SUBJECT_CODE_PATTERN = re.compile(r"\b[A-Z]{3,4}\d{3}\b")


def extract_subject_codes(text: str) -> set[str]:
    """
   scan md `text` for every UOW-style subject code and return them
    as a set, e.g. `{"CSIT114", "CSIT214", "CSIT321"}`.

    """
    return set(SUBJECT_CODE_PATTERN.findall(text))


# ===========================================================================
# Shared table helpers 
# ===========================================================================

# A divider row contains only `|`, `-`, `:`, and whitespace, e.g.
# `|---|---|---|` or `|:----|:--:|----:|`.
#(used for the md test records to strip the |)
#actual enrollment record wont use this as it tab separated input
_TABLE_DIVIDER = re.compile(r"^\s*\|[\s\-:|]+\|\s*$")


def _clean_cell(cell: str) -> str:
    """Strip whitespace and bold/italic markers from a markdown table cell."""
    return cell.strip().strip("*").strip()


def _iter_table_rows(lines: list[str], start_idx: int):
    """
    Yield cleaned-cell lists for each data row following `start_idx`.

    Stops at the first non-pipe line (including blank lines). Divider rows
    are skipped silently. Caller is responsible for popping the header row
    before calling — `start_idx` should point at the line *after* the header.
    """
    for line in lines[start_idx:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            return
        if _TABLE_DIVIDER.match(line):
            continue
        yield [_clean_cell(c) for c in stripped.strip("|").split("|")]


# ===========================================================================
# Study Plan Markdown Table Interpreter
# ===========================================================================

# Anchor: the system prompt fixes the table header at
#   `| Year | Session | Subject Code | Subject Name | CP | Notes |`.
# We match the first three columns case-insensitively to absorb minor LLM
# drift without losing the boundary signal.
_STUDY_PLAN_HEADER = re.compile(
    r"\|\s*Year\s*\|\s*Session\s*\|\s*Subject\s*Code\s*\|",
    re.IGNORECASE,
)


def parse_study_plan_table(markdown: str) -> list[ScheduledSubject]:
    """
    Locate the **Study Plan:** markdown table by anchoring on the
    `| Year | Session | Subject Code | ...` header, then iterate over data
    rows and parse each into a `ScheduledSubject`
    -a list of subjects will study.

    Parsing rules
    -------------
    - The first line matching the header anchor begins the table.
    - The next divider row (`|---|---|...`) is consumed and discarded.
    - Subsequent lines starting with `|` are treated as data rows.
    - The first non-pipe line (including a blank line) terminates the table.
    - Rows that fail to yield a valid Year (4-digit int), Subject Code
      (matching `SUBJECT_CODE_PATTERN`), or CP (int) are skipped rather than
      raising — validators flag structural breaches downstream.
    - Bold markers (`**...**`) are stripped from each cell before parsing.

    The `session` cell is preserved verbatim. The spec restricts plan sessions
    to "Autumn" or "Spring", but the parser stays permissive so a Phase 3
    validator can flag drift (e.g. an erroneous "Annual" CSIT321 row).
    """
    lines = markdown.splitlines()

    header_idx: int | None = None
    for i, line in enumerate(lines):
        if _STUDY_PLAN_HEADER.search(line):
            header_idx = i
            break

    if header_idx is None:
        return []

    rows: list[ScheduledSubject] = []

    for cells in _iter_table_rows(lines, header_idx + 1):
        if len(cells) < 5:
            continue  # need at least Year | Session | Code | Name | CP

        year_match = re.search(r"\d{4}", cells[0])
        if not year_match:
            continue
        year = int(year_match.group())

        code_match = SUBJECT_CODE_PATTERN.search(cells[2])
        if not code_match:
            continue
        subject_code = code_match.group()

        cp_match = re.search(r"\d+", cells[4])
        if not cp_match:
            continue
        credit_points = int(cp_match.group())

        rows.append(
            ScheduledSubject(
                year=year,
                session=cells[1],
                subject_code=subject_code,
                credit_points=credit_points,
                name=cells[3] if len(cells) > 3 else "",
                notes=cells[5] if len(cells) > 5 else "",
            )
        )

    return rows


# ===========================================================================
# Phase 3 prep — SOLS Enrolment Record Parsers
# ===========================================================================

# Per the seeded handbook's "Student Enrolment Record Format" section,
# a subject is Complete iff Status == "Complete" AND Grade ∈ {HD,D,C,P,PS,S}.
PASSING_GRADES: frozenset[str] = frozenset({"HD", "D", "C", "P", "PS", "S"})


_ENROLMENT_HEADER = re.compile(
    r"\|\s*Year\s*\|\s*Session\s*\|\s*Campus[/\s]*Delivery\s*\|\s*"
    r"Subject\s*Code\s*\|\s*Nom\s*CP\s*\|\s*Mark\s*\|\s*Grade\s*\|\s*Status\s*\|",
    re.IGNORECASE,
)

_SPECIFIED_HEADER = re.compile(
    r"\|\s*Course\s*\|\s*Subject\s*Code\s*\|\s*Name\s*\|\s*Level\s*\|\s*Nom\s*CP\s*\|",
    re.IGNORECASE,
)

_UNSPECIFIED_HEADER = re.compile(
    r"^\s*\|\s*Course\s*\|\s*Level\s*\|\s*Nom\s*CP\s*\|\s*$",
    re.IGNORECASE,
)


def parse_sols_enrolment(markdown: str) -> list[EnrolmentRow]:
    """
    Locate the SOLS Enrolment History table by anchoring on the
    `| Year | Session | Campus/Delivery | Subject Code | Nom CP | Mark | Grade | Status |`
    header and parse every data row into an `EnrolmentRow`.

    Rows that fail to yield a valid Year, Subject Code, or Nom CP are skipped.
    Blank `Mark` / `Grade` cells produce `None`. The `status` field is recorded
    verbatim so callers can branch on values like "Complete", "Enrolled",
    "Withdrawn", "Leave of Absence", or "Not Counted (Prior Course)".
    """
    lines = markdown.splitlines()

    header_idx: int | None = None
    for i, line in enumerate(lines):
        if _ENROLMENT_HEADER.search(line):
            header_idx = i
            break

    if header_idx is None:
        return []

    rows: list[EnrolmentRow] = []

    for cells in _iter_table_rows(lines, header_idx + 1):
        if len(cells) < 8:
            continue

        year_match = re.search(r"\d{4}", cells[0])
        if not year_match:
            continue
        year = int(year_match.group())

        code_match = SUBJECT_CODE_PATTERN.search(cells[3])
        if not code_match:
            continue
        subject_code = code_match.group()

        cp_match = re.search(r"\d+", cells[4])
        if not cp_match:
            continue
        nom_cp = int(cp_match.group())

        mark: int | None = None
        m = re.search(r"\d+", cells[5])
        if m:
            mark = int(m.group())

        grade_cell = cells[6]
        grade: str | None = grade_cell if grade_cell else None

        rows.append(
            EnrolmentRow(
                year=year,
                session=cells[1],
                campus_delivery=cells[2],
                subject_code=subject_code,
                nom_cp=nom_cp,
                mark=mark,
                grade=grade,
                status=cells[7],
            )
        )

    return rows


def parse_specified_credits(markdown: str) -> list[SpecifiedCredit]:
    """
    Locate the SOLS Specified Credit table by anchoring on the
    `| Course | Subject Code | Name | Level | Nom CP |` header and parse each
    row. Returns `[]` if the section is absent or contains only "None".
    """
    lines = markdown.splitlines()

    header_idx: int | None = None
    for i, line in enumerate(lines):
        if _SPECIFIED_HEADER.search(line):
            header_idx = i
            break

    if header_idx is None:
        return []

    rows: list[SpecifiedCredit] = []

    for cells in _iter_table_rows(lines, header_idx + 1):
        if len(cells) < 5:
            continue

        code_match = SUBJECT_CODE_PATTERN.search(cells[1])
        if not code_match:
            continue
        subject_code = code_match.group()

        level_match = re.search(r"\d+", cells[3])
        cp_match = re.search(r"\d+", cells[4])
        if not (level_match and cp_match):
            continue

        rows.append(
            SpecifiedCredit(
                course=cells[0],
                subject_code=subject_code,
                name=cells[2],
                level=int(level_match.group()),
                nom_cp=int(cp_match.group()),
            )
        )

    return rows


def parse_unspecified_credits(markdown: str) -> list[UnspecifiedCredit]:
    """
    Locate the SOLS Unspecified Credit table by anchoring on the exact
    `| Course | Level | Nom CP |` header (3 columns — the anchor is anchored
    to the full line to avoid false-matching the Specified table).
    """
    lines = markdown.splitlines()

    header_idx: int | None = None
    for i, line in enumerate(lines):
        if _UNSPECIFIED_HEADER.match(line):
            header_idx = i
            break

    if header_idx is None:
        return []

    rows: list[UnspecifiedCredit] = []

    for cells in _iter_table_rows(lines, header_idx + 1):
        if len(cells) < 3:
            continue

        level_match = re.search(r"\d+", cells[1])
        cp_match = re.search(r"\d+", cells[2])
        if not (level_match and cp_match):
            continue

        rows.append(
            UnspecifiedCredit(
                course=cells[0],
                level=int(level_match.group()),
                nom_cp=int(cp_match.group()),
            )
        )

    return rows


# ===========================================================================
# SOLS completion helpers
# ===========================================================================

def is_complete(row: EnrolmentRow) -> bool:
    """
    Per handbook §Student Enrolment Record Format: a row counts as complete
    iff Status is "Complete" AND Grade ∈ {HD, D, C, P, PS, S}.

    F, N, NH, W, WF, AF, and blank grades are explicitly NOT complete.
    Specified Credit is handled separately (see `parse_specified_credits` —
    every row in that table counts as complete by definition).
    """
    return row.status == "Complete" and row.grade in PASSING_GRADES


def completed_subject_codes(rows: list[EnrolmentRow]) -> set[str]:
    """Set of subject codes from SOLS enrolment history that count as complete."""
    return {row.subject_code for row in rows if is_complete(row)}


def completed_cp_from_history(rows: list[EnrolmentRow]) -> int:
    """Sum of CP from SOLS enrolment history rows that count as complete."""
    return sum(row.nom_cp for row in rows if is_complete(row))


def all_completed_subject_codes(sols_md: str) -> set[str]:
    """
    All subject codes the student already holds credit for in their SOLS:
    completed enrolment-history rows + every Specified Credit row.
    """
    history_codes = completed_subject_codes(parse_sols_enrolment(sols_md))
    specified_codes = {sc.subject_code for sc in parse_specified_credits(sols_md)}
    return history_codes | specified_codes


def total_completed_cp(sols_md: str) -> int:
    """
    Sum of CP from every SOLS source that counts toward the 144 CP degree
    requirement:

    - Enrolment History rows where Status == "Complete" and Grade ∈ passing
    - All Specified Credit rows (each counts as Complete per handbook §Format)
    - All Unspecified Credit CP (counts toward total, no specific subject)
    """
    history = completed_cp_from_history(parse_sols_enrolment(sols_md))
    specified = sum(sc.nom_cp for sc in parse_specified_credits(sols_md))
    unspecified = sum(uc.nom_cp for uc in parse_unspecified_credits(sols_md))
    return history + specified + unspecified


# ===========================================================================
# Full reply parser — later phase.
# ===========================================================================

def parse_reply(markdown: str) -> StudyPlan:
    """
    Parse a full Gemini reply (Audit block + Study Plan table + CP summary)
    into a `StudyPlan`. **Later-phase deliverable.** Until it lands, callers
    should compose `parse_study_plan_table` and `extract_subject_codes`
    directly.
    """
    raise NotImplementedError(
        "parse_reply is a later-phase deliverable; use parse_study_plan_table "
        "and extract_subject_codes directly until the full audit parser lands."
    )
