from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ChatProfile(BaseModel):
    degree_code: str | None = None
    major: str | None = None
    campus: str | None = None
    commencement_year: int | None = None
    elective_mode: Literal["degree", "interest"] | None = None
    elective_interests: list[str] | None = None


class ChatContext(BaseModel):
    profile: ChatProfile
    enrolment_record: str | None = None


class ChatRequest(BaseModel):
    message: str

    # Which model to answer with. None uses the session's model,
    # then the server default.
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


class TitleOut(BaseModel):
    title: str
