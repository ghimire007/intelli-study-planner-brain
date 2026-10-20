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
    
    # match = re.search(
    #     r"\b((?:19|20)\d{2})\s+"
    #     r"(?:Annual|Autumn|Spring|Summer|Winter)\b",
    #     text,
    #     re.IGNORECASE,
    # )
    
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

# import json
# import re

# from app.llm.text import as_text
# from pydantic import BaseModel, Field


# _COURSE_CODE_RE = re.compile(
#     r"\bCourse\s*:\s*(\d{3,4})(?!\d)",
#     re.IGNORECASE,
# )

# _CAMPUS_ALIASES = {
#     "wol": "Wollongong",
#     "wollongong": "Wollongong",
#     "uow wollongong": "Wollongong",
#     "liv": "Liverpool",
#     "liverpool": "Liverpool",
#     "uow liverpool": "Liverpool",
#     "sim": "Singapore",
#     "singapore": "Singapore",
#     "uowhk": "Hong Kong",
#     "hong kong": "Hong Kong",
#     "kdu": "Malaysia",
#     "malaysia": "Malaysia",
# }


# def _extract_degree_code(text: str) -> str | None:
#     """Extract a course code from an explicit SOLS Course header."""
#     match = _COURSE_CODE_RE.search(text)
#     return match.group(1) if match else None


# def _canonicalize_campus(value: str | None) -> str | None:
#     """Canonicalize a campus only when its value is recognized."""
#     if not value:
#         return None

#     return _CAMPUS_ALIASES.get(value.strip().casefold())

# def _extract_earliest_subject_year(text: str) -> int | None:
#     """Extract the earliest plausible year from SOLS subject rows."""
#     years = re.findall(
#         r"(?<!\d)(20\d{2})(?!\d)",
#         text,
#     )
#     return min(map(int, years)) if years else None

# _PARSER_MODEL_PROMPT = """
# Extract the student's degree metadata from the UOW SOLS enrolment record
# and/or information explicitly provided by the student.

# Return ONLY a JSON object — no explanation, no markdown, no code block.

# {
#   "degree_code": "string or null",
#   "year": "number or null",
#   "campus": "string or null",
#   "majors": ["string", "..."]
# }

# Rules:
# - degree_code is the course number (e.g. "766" or "1807"). Return null if you cannot find one you're confident in. Do not guess or default to 766.
# - year is the explicitly provided commencement year or, when not explicitly provided, the earliest year found in the subject list. Return null if it cannot be determined. Do not default to the current year.
# - campus is the canonical campus name:
#     "Wol", "Wollongong", "UOW Wollongong" -> "Wollongong"
#     "Liv", "Liverpool", "UOW Liverpool"   -> "Liverpool"
#     "SIM", "Singapore"                    -> "Singapore"
#     "UOWHK", "Hong Kong"                  -> "Hong Kong"
#     "KDU", "Malaysia"                     -> "Malaysia"
#   If the Campus column contains multiple distinct values, use the most recent (latest year) campus. Return null if it cannot be determined.
# - majors must contain EVERY explicitly listed major, preserving their full names. Return an empty list if no major is explicitly provided.
# - Recognise labels such as "Major", "Major 1", "Major 2", "Second Major", and "Major 1:" / "Major 2:" followed by values on the next line.
# - If multiple majors are listed, include all of them in their original order. Do not overwrite one major with another.
# - Do not infer a major from the course code, course title, subjects, or previous assumptions.
# - Do not invent, rename, or silently correct major names.
# - Return only the requested fields.
# """.strip()


# class SOLSMeta(BaseModel):
#     """Minimal metadata extracted from a SOLS paste — just enough to query the handbook.
#     degree_code/year are nullable: when the parser can't confidently extract them, the
#     agent asks the student directly instead of guessing."""
#     degree_code: str | None  # e.g. "766"
#     year: int | None         # commencement year — used for handbook DB lookup
#     campus: str | None            # canonical campus name e.g. "Wollongong", "Liverpool", "Singapore"
#     majors: list[str] = Field(default_factory=list)


# def _strip_code_block(text: str) -> str:
#     text = text.strip()
#     text = re.sub(r"^```(?:json)?\s*", "", text)
#     text = re.sub(r"\s*```$", "", text)
#     return text.strip()


# def meta_is_complete(meta: dict) -> bool:
#     """True if enough was confidently extracted to proceed without asking the student."""
#     return meta.get("degree_code") is not None and meta.get("year") is not None and meta.get("campus") is not None


# async def parse_sols(llm, protected_sols: str) -> SOLSMeta:
#     """Extract metadata, preferring explicit SOLS header values."""

#     import time

#     start = time.perf_counter()

#     # Extract the degree code deterministically before invoking the LLM.
#     print("RAW SOLS:", repr(protected_sols[:300]))
#     header_degree_code = _extract_degree_code(protected_sols)

#     print(
#         "parse_sols: explicit header degree_code =",
#         header_degree_code,
#     )
#     print("parse_sols: sending request")

#     response = await llm.ainvoke(
#         [
#             ("system", _PARSER_MODEL_PROMPT),
#             ("user", protected_sols),
#         ]
#     )

#     print("parse_sols: response received")
#     print(
#         f"parse_sols LLM took "
#         f"{time.perf_counter() - start:.2f}s"
#     )

#     data = json.loads(
#         _strip_code_block(as_text(response.content))
#     )

#     if data.get("year") is None:
#         data["year"] = _extract_earliest_subject_year(protected_sols)

#     # An explicit Course header is more reliable than an LLM omission.
#     if header_degree_code is not None:
#         data["degree_code"] = header_degree_code

#     # Canonicalize only recognized campus aliases.
#     campus = data.get("campus")
#     canonical_campus = _canonicalize_campus(campus)
#     if canonical_campus is not None:
#         data["campus"] = canonical_campus

#     print("parse_sols data: ", data)


#     # Validate the final result using the Pydantic model.
#     return SOLSMeta(**data)


# # async def parse_sols(llm, protected_sols: str) -> SOLSMeta:
# #     """Extract degree_code/year/campus from a raw SOLS paste via the LLM parser."""

# #     import time

# #     start = time.perf_counter()

# #     # structured_llm = llm.with_structured_output(SOLSMeta)
# #     print("parse_sols: sending request")
# #     response = await llm.ainvoke(
# #         [
# #             ("system", _PARSER_MODEL_PROMPT),
# #             ("user", protected_sols),
# #         ]
# #     )
# #     print("parse_sols: response received")

# #     print(
# #         f"parse_sols LLM took "
# #         f"{time.perf_counter() - start:.2f}s"
# #     )
# #     data = json.loads(_strip_code_block(as_text(response.content)))
# #     return SOLSMeta(**data)
