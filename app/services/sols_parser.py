# """Extracts degree_code/year/campus metadata from a raw SOLS enrolment paste.

# This is a domain/service concern (interpreting the SOLS record), kept separate
# from `agents/skills.py` (which only adapts services like this one into
# LangChain tool calls for the advisor agent).
# """


import re
from pydantic import BaseModel, Field


class SOLSMeta(BaseModel):
    degree_code: str | None = None
    year: int | None = None
    campus: str | None = None
    majors: list[str] = Field(default_factory=list)


def extract_sols_metadata(text: str) -> SOLSMeta:
    """Extract metadata from the original, PII-scrubbed SOLS text."""

    meta = SOLSMeta()

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