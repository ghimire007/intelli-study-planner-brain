"""Extracts degree_code/year/campus metadata from a raw SOLS enrolment paste.

This is a domain/service concern (interpreting the SOLS record), kept separate
from `agents/skills.py` (which only adapts services like this one into
LangChain tool calls for the advisor agent).
"""
import json
import re

from pydantic import BaseModel

from app.llm.text import as_text

_PARSER_MODEL_PROMPT = """
Extract the following three fields from the UOW SOLS enrolment record and return ONLY a JSON object — no explanation, no markdown, no code block.

{
  "degree_code": "string or null",
  "year": "number or null",
  "campus": "string or null"
}

Rules:
- degree_code is the course number (e.g. "766" or "1807"). Return null if you cannot find one you're confident in — do not guess and do not default to 766.
- year is the earliest year found in the subject list (the student's commencement year). Return null if it cannot be determined.
- campus is the canonical campus name — map as follows:
    "Wol", "Wollongong", "UOW Wollongong" → "Wollongong"
    "Liv", "Liverpool", "UOW Liverpool"   → "Liverpool"
    "SIM", "Singapore"                    → "Singapore"
    "UOWHK", "Hong Kong"                  → "Hong Kong"
    "KDU", "Malaysia"                     → "Malaysia"
  If the Campus column contains multiple distinct values, use the most recent (latest year) campus.
  If campus cannot be determined, default to "Wollongong" (do not return null for campus).
""".strip()


class SOLSMeta(BaseModel):
    """Minimal metadata extracted from a SOLS paste — just enough to query the handbook.
    degree_code/year are nullable: when the parser can't confidently extract them, the
    agent asks the student directly instead of guessing."""
    degree_code: str | None  # e.g. "766"
    year: int | None         # commencement year — used for handbook DB lookup
    campus: str              # canonical campus name e.g. "Wollongong", "Liverpool", "Singapore"


def _strip_code_block(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def meta_is_complete(meta: dict) -> bool:
    """True if enough was confidently extracted to proceed without asking the student."""
    return meta.get("degree_code") is not None and meta.get("year") is not None


async def parse_sols(llm, raw_sols: str) -> SOLSMeta:
    """Extract degree_code/year/campus from a raw SOLS paste via the LLM parser."""
    response = await llm.ainvoke(
        [
            ("system", _PARSER_MODEL_PROMPT),
            ("user", raw_sols),
        ]
    )
    data = json.loads(_strip_code_block(as_text(response.content)))
    return SOLSMeta(**data)
