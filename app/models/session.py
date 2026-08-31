import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
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

    # Nullable because sessions created before chat required a login have no owner.
    # Those rows are unreadable by design — we cannot prove who they belong to.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True, nullable=True
    )
    # Which model this conversation runs on, and the credential it was pinned to,
    # so a long chat keeps using one key even if the student changes their default.
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("llm_credential.id", ondelete="SET NULL"), nullable=True
    )
