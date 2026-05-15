import re
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()

_TEST_RECORDS_DIR = Path(__file__).parent.parent.parent / "test_records"


class TestRecordOut(BaseModel):
    id: str
    label: str
    student: str
    course: str
    major: str
    delivery: str
    note: str | None
    second_major: str | None
    honours_gpa: str | None
    content: str


def _prettify(stem: str) -> str:
    return stem.replace("_", " ").title()


def _extract(pattern: str, text: str, default: str = "") -> str:
    m = re.search(pattern, text)
    return m.group(1).strip().rstrip("*").strip() if m else default


def _parse(stem: str, content: str) -> TestRecordOut:
    student = _extract(r"\*\*Student:\*\*\s*(.+)", content)
    course = _extract(r"\*\*Course:\*\*\s*(.+)", content)
    major = _extract(r"\*\*Major:\*\*\s*(.+)", content)
    campus_line = _extract(r"\*\*Campus:\*\*\s*(.+)", content)
    delivery_match = re.search(r"\*\*Delivery:\*\*\s*([^|]+)", campus_line)
    delivery = delivery_match.group(1).strip() if delivery_match else "On Campus"
    note = _extract(r"\*\*Note:\*\*\s*(.+)", content) or None
    second_major = _extract(r"\*\*Second Major:\*\*\s*(.+)", content) or None
    honours_gpa = _extract(r"\*\*Honours GPA \(Bachelor\):\s*(.+)", content) or None

    return TestRecordOut(
        id=stem,
        label=_prettify(stem),
        student=student,
        course=course,
        major=major,
        delivery=delivery,
        note=note,
        second_major=second_major,
        honours_gpa=honours_gpa,
        content=content,
    )


@router.get("", response_model=list[TestRecordOut])
async def list_test_records() -> list[TestRecordOut]:
    records = []
    for path in sorted(_TEST_RECORDS_DIR.glob("*.md")):
        records.append(_parse(path.stem, path.read_text()))
    return records
