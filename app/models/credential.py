"""Stored LLM credentials — one row per key a student brings, plus an audit trail.

The row holds no readable key: ``key_ciphertext`` is the sealed secret and
``dek_wrapped`` the data key that opens it, both produced by app/core/crypto.py.
``last4`` exists purely so the settings page can show a recognisable "…ab12".
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base


class CredentialStatus(StrEnum):
    ACTIVE = "active"
    #: The provider rejected it in use — the student must replace it.
    INVALID = "invalid"
    REVOKED = "revoked"


class AuditAction(StrEnum):
    CREATED = "created"
    ROTATED = "rotated"
    RELABELLED = "relabelled"
    DEFAULT_SET = "default_set"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DELETED = "deleted"


class LLMCredential(Base):
    __tablename__ = "llm_credential"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(100), nullable=False)

    # ── where the secret lives ───────────────────────────────────────────────
    #: "local" (sealed in the columns below) or "infisical" (secret_ref below).
    #: Recorded per row, so one table can hold both and a switch is not a migration.
    backend: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    #: The Infisical secret name. NULL for locally sealed rows.
    secret_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ── the sealed secret (local backend only) ───────────────────────────────
    key_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    dek_wrapped: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    dek_nonce: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    #: Which master key wrapped dek_wrapped. Lets rotation run without downtime.
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    last4: Mapped[str] = mapped_column(String(8), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CredentialStatus.ACTIVE.value
    )

    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship()  # noqa: F821 — resolved via app.models

    __table_args__ = (
        UniqueConstraint("user_id", "provider", "label", name="uq_llm_credential_label"),
        # "exactly one default per provider per user", enforced by the database
        # rather than by application code that can race with itself.
        Index(
            "uq_llm_credential_default",
            "user_id",
            "provider",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )


class LLMCredentialAudit(Base):
    """Append-only trail of what happened to a credential.

    ``credential_id`` is intentionally not a foreign key: the trail has to outlive
    the credential it describes, including a delete.
    """

    __tablename__ = "llm_credential_audit"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), index=True, nullable=False
    )
    credential_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
