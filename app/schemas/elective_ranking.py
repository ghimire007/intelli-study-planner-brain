from typing import Literal

from pydantic import BaseModel, Field

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


class RankedElectivesWithSubjects(BaseModel):
    """Ranking shortlist plus official subject cards for those codes."""

    mode: str
    pools: list[ElectivePoolPriorities]
    subject_cards: str
