"""Read-only handbook data: seeded course handbooks, structured course rules,
subject/major cards and UOW policy topics (honours, Dean's Scholar, ...).

Public like /planning — it only serves published UOW handbook content.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.handbook import Handbook
from app.schemas.handbook import (
    CatalogEntryOut,
    CourseRulesOut,
    HandbookOut,
    HandbookSummaryOut,
    PolicyOut,
    PolicyTopicOut,
)
from app.services.course_rules import load_course_rules
from app.services.elective_pools import load_elective_pools
from app.services.handbook_service import find_handbook, list_handbooks
from app.services.kb_service import find_major, find_subject
from app.services.knowledge_service import TOPICS, load_topic

router = APIRouter()

DEFAULT_YEAR = 2026


def _title(handbook: Handbook) -> str:
    first_line = handbook.information.lstrip().split("\n", 1)[0]
    return first_line.lstrip("# ").strip()


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


@router.get("/courses", response_model=list[HandbookSummaryOut])
async def list_courses(db: AsyncSession = Depends(get_db)) -> list[HandbookSummaryOut]:
    return [
        HandbookSummaryOut(course=h.course, year=h.year, campus=h.campus, title=_title(h))
        for h in await list_handbooks(db)
    ]


@router.get("/courses/{course}", response_model=HandbookOut)
async def get_course(
    course: str,
    campus: str = "Wollongong",
    year: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> HandbookOut:
    handbook = await find_handbook(db, course, campus, year)
    if handbook is None:
        raise _not_found(f"No handbook found for course {course}.")
    return HandbookOut(
        course=handbook.course,
        year=handbook.year,
        campus=handbook.campus,
        title=_title(handbook),
        information=handbook.information,
    )


@router.get("/courses/{course}/rules", response_model=CourseRulesOut)
async def get_course_rules(course: str, campus: str = "Wollongong") -> CourseRulesOut:
    try:
        rules = load_course_rules(course, campus)
    except FileNotFoundError:
        raise _not_found(f"No course rules found for course {course}.") from None
    except ValueError:
        raise _not_found(f"Course {course} has no {campus} structure.") from None
    return CourseRulesOut(
        course=rules.course,
        campus=rules.campus,
        year=rules.year,
        total_cp=rules.total_cp,
        max_100_level_cp=rules.max_100_level_cp,
        capstone_code=rules.capstone_code,
        capstone_cp=rules.capstone_cp,
        core_subjects=sorted(rules.core_subjects),
        core_selection=sorted(rules.core_selection),
        replacement_for=rules.replacement_for,
        major_core={code: sorted(subjects) for code, subjects in rules.major_core.items()},
        elective_pools=load_elective_pools(course).get("pools", []),
    )


@router.get("/subjects/{code}", response_model=CatalogEntryOut)
async def get_subject(
    code: str, year: int = DEFAULT_YEAR, db: AsyncSession = Depends(get_db)
) -> CatalogEntryOut:
    subject = await find_subject(db, code, year)
    if subject is None:
        raise _not_found(f"No subject found with code {code}.")
    return CatalogEntryOut.model_validate(subject)


@router.get("/majors/{code}", response_model=CatalogEntryOut)
async def get_major(
    code: str, year: int = DEFAULT_YEAR, db: AsyncSession = Depends(get_db)
) -> CatalogEntryOut:
    major = await find_major(db, code, year)
    if major is None:
        raise _not_found(f"No major found with code {code}.")
    return CatalogEntryOut.model_validate(major)


@router.get("/policies", response_model=list[PolicyTopicOut])
async def list_policies() -> list[PolicyTopicOut]:
    return [PolicyTopicOut(slug=t.slug, description=t.description) for t in TOPICS]


@router.get("/policies/{topic}", response_model=PolicyOut)
async def get_policy(topic: str) -> PolicyOut:
    match = next((t for t in TOPICS if t.slug == topic), None)
    if match is None:
        raise _not_found(f"No policy topic {topic}.")
    return PolicyOut(slug=match.slug, description=match.description, content=load_topic(topic))
