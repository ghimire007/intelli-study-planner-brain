from typing import Literal

from pydantic import BaseModel


class ConfirmedMetadata(BaseModel):
    """What `confirm_metadata_tool` returns. Only the fields the tool was given
    are set, and dumped with `exclude_unset`, so omitted fields keep the
    student's known values downstream. `major` is the legacy single-major alias."""

    degree_code: str | None = None
    year: int | None = None
    campus: str | None = None
    majors: list[str] | None = None
    major: str | None = None


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
