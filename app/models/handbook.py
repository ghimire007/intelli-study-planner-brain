from sqlalchemy import BigInteger, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Handbook(Base):
    __tablename__ = "handbook"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    course: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    campus: Mapped[str] = mapped_column(String(100), nullable=False, index=True, default="Wollongong")
    information: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("year", "course", "campus", name="uq_handbook_year_course_campus"),
    )
