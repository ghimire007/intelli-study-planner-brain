"""Deterministic checks on the model's required/core subject list.

The schema catches a malformed answer; the domain checks compare what the
model wrote with the subject catalog and the student's record, which is exact
where an LLM auditor is not.
"""
import re

from app.schemas.core_subjects import CoreSubjectList
from app.services.enrolment import UnreadableRecord, parse_enrolment

_CODE_IN_TEXT = re.compile(r"\b[A-Z]{2,4}\d{3}[A-Z]?\b")
_FAILED_GRADES = frozenset({"F", "TF"})


def codes_in_record(raw_sols: str | None) -> set[str]:
    """Subjects already passed, in progress, or credited. Failed attempts are
    not here: they have to be taken again."""
    if not raw_sols or raw_sols == "no enrolment yet":
        return set()
    try:
        record = parse_enrolment(raw_sols)
    except UnreadableRecord:
        return set()

    codes = {
        row.code
        for row in record.rows
        if row.status == "Enrolled" or (row.status == "Complete" and row.grade not in _FAILED_GRADES)
    }
    codes.update(credit.code for credit in record.specified_credit if credit.code)
    return codes


def codes_in_text(text: str | None) -> set[str]:
    return set(_CODE_IN_TEXT.findall(text or ""))


def validate_core_subjects(
    core: CoreSubjectList,
    *,
    catalog: dict[str, dict],
    handbook_codes: set[str],
    record_codes: set[str],
) -> list[str]:
    """Return one message per problem; an empty list means the list is sound.

    A code is accepted if the catalog or the handbook text the model was given
    knows it, so placeholder codes that only the handbook mentions pass.
    """
    known = {code.upper().replace(" ", "") for code in catalog} | handbook_codes
    issues: list[str] = []

    for subject in core.subjects:
        if subject.code not in known:
            issues.append(f"{subject.code} is not in the handbook or subject catalog.")
            continue

        if subject.code in record_codes:
            issues.append(f"{subject.code} is already in the student record; remove it.")

        entry = catalog.get(subject.code)
        catalog_cp = entry.get("cp") if entry else None
        if catalog_cp is not None and str(catalog_cp).isdigit() and int(catalog_cp) != subject.credit_points:
            issues.append(
                f"{subject.code} has {subject.credit_points} credit points; "
                f"the catalog lists {catalog_cp}."
            )

    return issues
