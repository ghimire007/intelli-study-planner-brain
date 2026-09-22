"""Handbook lookup — a persistence/domain concern, kept separate from
`agents/skills.py` (which only adapts this into a LangChain tool call).
"""
from app.models.handbook import Handbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class HandbookUnavailable(ValueError):
    """Rules are unavailable, not a missing conversation."""


async def find_handbook(
    db: AsyncSession, degree_code: str, campus: str, year: int | None = None
) -> Handbook | None:
    """Newest handbook row for a degree (at or below *year* when given),
    preferring an exact campus match and falling back to any campus."""
    for campus_filter in [campus, None]:
        query = (
            select(Handbook)
            .where(Handbook.course == degree_code)
            .order_by(Handbook.year.desc())
        )
        if campus_filter is not None:
            query = query.where(Handbook.campus == campus_filter)
        if year is not None:
            query = query.where(Handbook.year <= year)
        result = await db.execute(query.limit(1))
        handbook = result.scalar_one_or_none()
        if handbook:
            return handbook
    return None


async def list_handbooks(db: AsyncSession) -> list[Handbook]:
    result = await db.execute(
        select(Handbook).order_by(Handbook.course, Handbook.year.desc(), Handbook.campus)
    )
    return list(result.scalars())


async def fetch_handbook(db: AsyncSession, degree_code: str, year: int, campus: str) -> str:
    """Fetch the handbook markdown for a degree, preferring an exact campus match."""
    handbook = await find_handbook(db, degree_code, campus)
    if handbook is None:
        raise HandbookUnavailable(f"No handbook found for course {degree_code}")
    return handbook.information
