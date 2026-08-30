"""The resolved answer to "which key, which model" for one request.

Deliberately tiny and deliberately not a pydantic model: an ``LLMConfig`` holds a
readable API key, so it must never be serialised into a response, a log line, or
LangGraph's checkpointer. ``api_key`` is excluded from ``repr`` so an accidental
``print(cfg)`` or a traceback frame cannot leak it.
"""
import uuid
from dataclasses import dataclass, field

from app.llm.registry import Provider


@dataclass(frozen=True)
class LLMConfig:
    provider: Provider
    model: str
    api_key: str = field(repr=False)
    #: The credential this key came from. None means the project's own fallback key.
    credential_id: uuid.UUID | None = None

    def __str__(self) -> str:  # keep f-strings from leaking the key too
        return repr(self)
