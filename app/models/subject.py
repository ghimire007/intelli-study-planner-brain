from sqlalchemy import JSON, BigInteger, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Subject(Base):
    """One UOW subject per handbook year, scraped from CourseLoop.

    `card` is the compact markdown summary returned to the agent by
    lookup_subjects_tool; `data` keeps the full scraped JSON (rules,
    offerings) for anything that later wants structure over prose.
    """
    __tablename__ = "subject"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    credit_points: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    card: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)

    __table_args__ = (UniqueConstraint("year", "code", name="uq_subject_year_code"),)
