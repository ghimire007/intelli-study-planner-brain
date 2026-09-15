from pydantic import BaseModel, Field


class StudentEligibilityInput(BaseModel):
    completed_subjects: list[str] = Field(default_factory=list)
    planned_subjects: list[str] = Field(default_factory=list)
    course: str = "766"
    major: str | None = None
    session: str
    campus: str = "Wollongong"


class EligibleSubjectOut(BaseModel):
    code: str
    title: str
    cp: int
    subject_level: str
    campus: str
    session: str
    in_core: bool = False
    in_major: bool = False


class EligibilityResult(BaseModel):
    eligible_subjects: list[EligibleSubjectOut]
