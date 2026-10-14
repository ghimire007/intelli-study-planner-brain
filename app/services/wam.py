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

from app.services.enrolment import MarkedEnrolmentRow, parse_enrolment
from pydantic import BaseModel

TECHNICAL_FAIL_MARK = 49

# Statuses whose result is final. Anything else (enrolled, withdrawn, withheld,
# a prior course the subject was not counted in) has no result to average.
_COUNTED_STATUSES = frozenset({"Complete", "Failed"})


class WamResult(BaseModel):
    wam: Decimal | None
    total_credit_points: int


def _mark_for(row: MarkedEnrolmentRow) -> int | None:
    if row.mark is not None:
        return row.mark
    if row.grade == "TF":
        return TECHNICAL_FAIL_MARK
    return None


def calculate_wam(raw_sols: str) -> WamResult:
    """Raises UnreadableRecord when the paste cannot be parsed."""
    record = parse_enrolment(raw_sols, keep_marks=True)

    total_cp = 0
    weighted = 0
    for row in record.rows:
        mark = _mark_for(row) if row.status in _COUNTED_STATUSES else None
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
