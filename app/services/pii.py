"""Scrub personally identifiable information from a raw SOLS enrolment paste.

Per sponsor guidance: grades/marks stay (needed to know whether a subject is
complete), but the student's name, student number, and similar identifiers must
never be stored or sent to the LLM. Applied once, at session start, before the
record enters the checkpointer or a prompt.
"""
import re

# "**Student:** Mr Daniel OKONKWO (9045623)" or "Student: Jane Doe 1234567"
_STUDENT_LINE = re.compile(
    r"^(\s*\**\s*Student(?:\s*Name)?\s*:?\**\s*).*$",
    re.IGNORECASE | re.MULTILINE,
)

# Standalone 7-8 digit student numbers, bare or in parentheses.
_STUDENT_NUMBER = re.compile(r"\(?\b\d{7,8}\b\)?")

# Common contact PII that can appear on exported records.
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?61|0)[\s-]?[2-478](?:[\s-]?\d){8}(?!\d)")


def scrub_pii(raw_sols: str) -> str:
    """Return the SOLS text with name/student-number/contact details redacted.

    Academic content (subject codes, marks, grades, statuses, campuses) is
    left untouched.
    """
    text = _STUDENT_LINE.sub(r"\1[REDACTED]", raw_sols)
    text = _STUDENT_NUMBER.sub("[REDACTED]", text)
    text = _EMAIL.sub("[REDACTED]", text)
    text = _PHONE.sub("[REDACTED]", text)
    return text
