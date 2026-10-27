# """Extracts degree_code/year/campus metadata from a raw SOLS enrolment paste.

# This is a domain/service concern (interpreting the SOLS record), kept separate
# from `agents/skills.py` (which only adapts services like this one into
# LangChain tool calls for the advisor agent).
# """


import re

from app.services.enrolment import UnreadableRecord, parse_enrolment
from pydantic import BaseModel, Field


class SOLSMeta(BaseModel):
    degree_code: str | None = None
    year: int | None = None
    campus: str | None = None
    majors: list[str] = Field(default_factory=list)


def extract_sols_metadata(text: str) -> SOLSMeta:
    """Extract metadata from the original, PII-scrubbed SOLS text."""

    meta = SOLSMeta()

    # Use the same reader as the privacy projection, including flattened SOLS
    # pastes. Effective dates and unrelated numbers must not supply the year.
    try:
        record = parse_enrolment(text)
    except UnreadableRecord:
        record = None
    if record is not None:
        campuses = {row.campus for row in record.rows}
        meta = SOLSMeta(
            degree_code=record.course_code,
            year=min((row.year for row in record.rows), default=None),
            campus=record.campus or (next(iter(campuses)) if len(campuses) == 1 else None),
            majors=record.majors,
        )
        explicit_year = re.search(
            r"(?i)\bcommencement(?:\s+year)?\s*:\s*((?:19|20)\d{2})\b", text
        )
        if explicit_year:
            meta.year = int(explicit_year.group(1))
        return meta

    # find degree code
    match = re.search(
        r"(?im)^\s*Course\s*:\s*(\d{3,4})(?!\d)",
        text,
    )
    if match:
        meta.degree_code = match.group(1)

    # find campus
    match = re.search(
        r"(?im)^\s*Campus\s*:\s*"
        r"(Wollongong|Sydney|Liverpool|Batemans Bay|"
        r"Bega|Southern Highlands|Shoalhaven|"
        r"South Western Sydney|Online)\b",
        text,
    )
    if match:
        meta.campus = match.group(1).strip()

    # find first year
    match = re.findall(
        r"(?<!\d)(20\d{2})(?!\d)",
        text,
    )

    if match:
        meta.year = int(min(map(int, match)))

    # get major/s
    for match in re.finditer(
        r"(?im)^\s*Major(?:\s+\d+)?\s*:\s*(.+?)\s*$",
        text,
    ):
        major = match.group(1).strip()
        if major and major not in meta.majors:
            meta.majors.append(major)

    return meta
