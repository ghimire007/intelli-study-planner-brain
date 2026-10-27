"""Structured plan shared by the chat table, Study Plan panel and PDF export."""
from pydantic import BaseModel, ConfigDict, Field


class PlannedSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=24)
    name: str = Field(min_length=1, max_length=200)
    cp: float = Field(ge=0, le=100)
    notes: str | None = Field(default=None, max_length=1000)


class PlannedSession(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session: str = Field(min_length=1, max_length=40)
    subjects: list[PlannedSubject] = Field(max_length=30)


class PlannedYear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: str = Field(min_length=1, max_length=20)
    sessions: list[PlannedSession] = Field(max_length=8)


class StudyPlanContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: list[PlannedYear] = Field(min_length=1, max_length=20)
