"""UOW Weighted Average Mark, computed from a SOLS enrolment paste.

Follows https://www.uow.edu.au/student/admin/wam/ : the sum of (credit points x
mark) over the sum of credit points. Fail grades count, with a technical fail
(TF) entered as 49. Credit from other institutions carries no mark and is not
entered. WAMs are not rounded up, so the result is truncated, never rounded.

This module is deliberately LLM-free. Marks and grades are read from the paste
here and nowhere else; the chat path projects them away (see enrolment.py).
"""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from app.services.enrolment import MarkedEnrolmentRow, UnreadableRecord, parse_enrolment
from pydantic import BaseModel

TECHNICAL_FAIL_MARK = 49

# Statuses whose result is final. Anything else (enrolled, withdrawn, withheld,
# a prior course the subject was not counted in) has no result to average.
_COUNTED_STATUSES = frozenset({"Complete", "Failed"})


# Only the unambiguous edge of the grade bands: F is below 50 and every passing
# grade is 50 or more. The boundaries between HD/D/C/P are not checked, since
# they are not something we can confirm. A mark on the wrong side of 50 for its
# grade means the paste is corrupted or misaligned, and a WAM from it would be
# wrong without looking wrong.
_MARKED_GRADES = frozenset({"HD", "D", "C", "P", "F"})
_PASS_MARK = 50


class WamResult(BaseModel):
    wam: Decimal | None
    total_credit_points: int


def _mark_for(row: MarkedEnrolmentRow) -> int | None:
    if row.mark is not None:
        return row.mark
    if row.grade == "TF":
        return TECHNICAL_FAIL_MARK
    return None


def _checked_mark(row: MarkedEnrolmentRow) -> int | None:
    """The mark to count, or UnreadableRecord when the row cannot be trusted."""
    label = f"{row.code} ({row.year} {row.session})"

    if row.mark is None and row.grade in _MARKED_GRADES:
        raise UnreadableRecord(
            f"{label} has a grade but no mark, so the WAM cannot be calculated. "
            "Paste the record again with the Mark column included."
        )

    if row.mark is not None and row.grade in _MARKED_GRADES:
        if (row.mark >= _PASS_MARK) != (row.grade != "F"):
            raise UnreadableRecord(
                f"{label} has mark {row.mark} but grade {row.grade}, which do not match. "
                "The record may be corrupted; paste it again."
            )

    return _mark_for(row)


def _unique(rows: list[MarkedEnrolmentRow]) -> list[MarkedEnrolmentRow]:
    """Drop exact repeats (a record pasted twice); refuse conflicting ones."""
    seen: dict[tuple[int, str, str], MarkedEnrolmentRow] = {}
    for row in rows:
        key = (row.year, row.session, row.code)
        if key not in seen:
            seen[key] = row
        elif (seen[key].mark, seen[key].nom_cp) != (row.mark, row.nom_cp):
            raise UnreadableRecord(
                f"{row.code} appears twice for {row.year} {row.session} with different results. "
                "Paste the record again."
            )
    return list(seen.values())


def calculate_wam(raw_sols: str) -> WamResult:
    """Raises UnreadableRecord when the paste cannot be parsed."""
    record = parse_enrolment(raw_sols, keep_marks=True)

    total_cp = 0
    weighted = 0
    for row in _unique(record.rows):
        mark = _checked_mark(row) if row.status in _COUNTED_STATUSES else None
        if mark is not None:
            total_cp += row.nom_cp
            weighted += row.nom_cp * mark

    wam = (Decimal(weighted) / Decimal(total_cp)).quantize(Decimal("0.01"), rounding=ROUND_DOWN) if total_cp else None
    return WamResult(wam=wam, total_credit_points=total_cp)


def summarise_for_chat(result: WamResult) -> str:
    """The note a chat session gets after a WAM run: the WAM and credit points only.

    No subject codes and no individual marks or grades. The WAM and credit total
    carry no personal identifiers, so the advisor may use them in follow-ups.
    """
    if result.wam is None:
        return (
            "I ran the WAM calculator on your record, but none of your subjects have a "
            "final mark yet, so there is no WAM to report."
        )
    return (
        f"I calculated your UOW WAM: {result.wam} across {result.total_credit_points} credit points. "
        "WAMs are truncated, not rounded up, and this is a guide only."
    )
