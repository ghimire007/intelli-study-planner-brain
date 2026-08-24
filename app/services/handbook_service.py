"""Handbook lookup — a persistence/domain concern, kept separate from
`agents/skills.py` (which only adapts this into a LangChain tool call).
"""
from app.models.handbook import Handbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def fetch_handbook(db: AsyncSession, degree_code: str, year: int, campus: str) -> str:
    """Fetch the handbook markdown for a degree, preferring an exact campus match."""
    for campus_filter in [campus, None]:
        query = (
            select(Handbook)
            .where(Handbook.course == degree_code)
            .order_by(Handbook.year.desc())
        )
        if campus_filter is not None:
            query = query.where(Handbook.campus == campus_filter)
        result = await db.execute(query.limit(1))
        handbook = result.scalar_one_or_none()
        if handbook:
            return handbook.information
    raise ValueError(f"No handbook found for course {degree_code}")
