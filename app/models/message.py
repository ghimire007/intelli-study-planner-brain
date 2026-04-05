import enum
import uuid
from datetime import datetime
from decimal import Decimal
from sqlalchemy import (
    BigInteger, DateTime, Enum as SAEnum, ForeignKey,
    Integer, JSON, Numeric, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base


class MessageRole(str, enum.Enum):
    system = "system"
    user = "user"
    assistant = "assistant"


class LLMProvider(str, enum.Enum):
    gemini = "gemini"
    anthropic = "anthropic"
    openai = "openai"


class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_session.id"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(SAEnum(MessageRole), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)  # plain text — for user/system or joined text of assistant turn
    parts: Mapped[list | None] = mapped_column(JSON, nullable=True)  # full raw parts array — set for assistant messages, null otherwise
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # LLM metadata — null for user/system messages
    provider: Mapped[LLMProvider | None] = mapped_column(SAEnum(LLMProvider), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cached_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 8), nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    session: Mapped["ChatSession"] = relationship(  # noqa: F821
        "ChatSession", back_populates="messages"
    )
