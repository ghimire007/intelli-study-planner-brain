"""Subject/major knowledge-base lookups — persistence concerns behind the
lookup_subjects/lookup_major agent skills (see agents/skills.py).

Each lookup returns the pre-built markdown `card` for the row, preferring the
newest year at or below the requested handbook year.
"""
from app.models.major import Major
from app.models.subject import Subject
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def find_subject(db: AsyncSession, code: str, year: int) -> Subject | None:
    result = await db.execute(
        select(Subject)
        .where(Subject.code == code.upper().strip(), Subject.year <= year)
        .order_by(Subject.year.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_major(db: AsyncSession, major_code: str, year: int) -> Major | None:
    result = await db.execute(
        select(Major)
        .where(Major.code == major_code.upper().strip(), Major.year <= year)
        .order_by(Major.year.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def fetch_subjects(db: AsyncSession, codes: list[str], year: int) -> str:
    """Return the markdown cards for the given subject codes, joined together.
    Unknown codes are reported rather than silently dropped."""
    cards: list[str] = []
    for code in codes:
        subject = await find_subject(db, code, year)
        cards.append(
            subject.card if subject
            else f"# {code}\n\nNo data found for subject code {code} — do not invent details for it."
        )
    return "\n---\n".join(cards)


async def fetch_major(db: AsyncSession, major_code: str, year: int) -> str:
    major = await find_major(db, major_code, year)
    if major is None:
        known = await db.execute(select(Major.code, Major.title).order_by(Major.code))
        listing = "\n".join(f"- {code}: {title}" for code, title in known)
        return (
            f"No major found with code {major_code}. Known majors:\n{listing}\n"
            "Pick the matching code and call this tool again."
        )
    return major.card
