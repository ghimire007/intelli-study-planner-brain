from typing import Literal

from pydantic import BaseModel


class ConfirmedMetadata(BaseModel):
    """What `confirm_metadata_tool` returns. `major` is the wire name the
    sanitiser already reads."""

    degree_code: str
    year: int
    campus: str
    major: list[str]


class PlanChangeRequest(BaseModel):
    """What `request_plan_change_tool` returns."""

    change_type: Literal[
        "major",
        "elective_preference",
        "course",
        "campus",
        "commencement_year",
        "session",
        "general_revision",
    ]
    major: list[str] | None = None
    elective_preference: str | None = None
    course: str | None = None
    campus: str | None = None
    commencement_year: int | None = None
    session: str | None = None
