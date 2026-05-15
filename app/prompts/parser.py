PARSER_PROMPT = """
Extract the following three fields from the UOW SOLS enrolment record and return ONLY a JSON object — no explanation, no markdown, no code block.

{
  "degree_code": "string",
  "year": number,
  "campus": "string"
}

Rules:
- degree_code is the course number, e.g. "766"
- year is the earliest year found in the subject list (the student's commencement year)
- campus is the canonical campus name — map as follows:
    "Wol", "Wollongong", "UOW Wollongong" → "Wollongong"
    "Liv", "Liverpool", "UOW Liverpool"   → "Liverpool"
    "SIM", "Singapore"                    → "Singapore"
    "UOWHK", "Hong Kong"                  → "Hong Kong"
    "KDU", "Malaysia"                     → "Malaysia"
  If the Campus column contains multiple distinct values, use the most recent (latest year) campus.
  If campus cannot be determined, default to "Wollongong".
""".strip()
