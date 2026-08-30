from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ChatRequest(BaseModel):
    message: str
    #: Which model to answer with. None uses the session's model, then the
    #: server default. The provider — and so the key — follows from the model.
    model: str | None = None


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
