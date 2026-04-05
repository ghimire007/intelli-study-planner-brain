import uuid
from datetime import datetime
from sqlalchemy import String, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from app.core.database import Base


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    degree_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    messages: Mapped[list["ChatMessage"]] = relationship(  # noqa: F821
        "ChatMessage", back_populates="session", order_by="ChatMessage.created_at"
    )
