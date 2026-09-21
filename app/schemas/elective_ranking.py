from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.eligibility import StudentEligibilityInput


class ElectivePriorityInput(StudentEligibilityInput):
    mode: Literal["major", "interest"]
    interests: str | None = None
    limit: int = Field(default=25, ge=1, le=100)


class RankedElectiveOut(BaseModel):
    code: str
    title: str
    score: float


class ElectivePoolPriorities(BaseModel):
    pool_id: str
    title: str
    cp: int | None = None
    priorities: list[RankedElectiveOut]


class ElectivePriorityResult(BaseModel):
    mode: str
    pools: list[ElectivePoolPriorities]


class Stage1ElectiveSubject(BaseModel):
    """Flat elective row for graphAPI Stage-1 state / eval."""

    model_config = ConfigDict(populate_by_name=True)

    code: str
    title: str
    name: str
    cp: int
    credit_points: int
    campus: str
    session: str
    valid_sessions: str
    pool_id: str
    score: float
    pre_requisites: str = Field(alias="pre-requisites")
    co_requisites: str = Field(alias="co-requisites")


class Stage1ElectiveList(BaseModel):
    subjects: list[Stage1ElectiveSubject]


class RankedElectivesWithSubjects(BaseModel):
    """Ranking shortlist, Stage-1 subject rows, and official subject cards."""

    mode: str
    pools: list[ElectivePoolPriorities]
    subjects: list[Stage1ElectiveSubject]
    subject_cards: str
