from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AcademicProfileContext(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    degree_code: str | None = Field(default=None, pattern=r"^\d{3,4}$")
    major: str | None = Field(default=None, min_length=1, max_length=120)
    campus: str | None = Field(default=None, min_length=1, max_length=32)
    commencement_year: int | None = Field(default=None, ge=1900, le=2100, strict=True)
    elective_interests: list[str] | None = Field(default=None, max_length=100)

    @field_validator("elective_interests")
    @classmethod
    def validate_interests(cls, value):
        if value is not None and any(not item.strip() or len(item) > 120 for item in value):
            raise ValueError("Interests must contain 1-120 characters each")
        return value


class ChatContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: AcademicProfileContext | None = None
    enrolment_record: str | None = Field(default=None, min_length=1, max_length=100_000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=100_000)
    input_type: Literal["enrolment", "question"] = "enrolment"
    #: Which model to answer with. None uses the session's model, then the
    #: server default. The provider — and so the key — follows from the model.
    model: str | None = None
    context: ChatContext | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | str
    role: str
    content: str
    created_at: datetime
    provider: str | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cached_tokens: int | None = None
    cost_usd: float | None = None


class StartSessionOut(BaseModel):
    session_id: str
    reply: MessageOut


class ContinueSessionOut(BaseModel):
    session_id: str
    reply: MessageOut


class HistoryOut(BaseModel):
    session_id: str
    degree_code: str
    model: str | None = None
    messages: list[MessageOut]
