PARSER_PROMPT = """
Extract the following two fields from the UOW SOLS enrolment record and return ONLY a JSON object — no explanation, no markdown, no code block.

{
  "degree_code": "string",
  "year": number
}

Rules:
- degree_code is the course number, e.g. "766"
- year is the earliest year found in the subject list (the student's commencement year)
""".strip()
