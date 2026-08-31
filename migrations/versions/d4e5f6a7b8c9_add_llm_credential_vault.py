"""add llm credential vault and give chat sessions an owner

Revision ID: d4e5f6a7b8c9
Revises: f8a9b0c1d2e3
Create Date: 2026-08-28
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "f8a9b0c1d2e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_credential",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("key_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("dek_wrapped", sa.LargeBinary(), nullable=False),
        sa.Column("dek_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last4", sa.String(length=8), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "provider", "label", name="uq_llm_credential_label"),
    )
    op.create_index("ix_llm_credential_user_id", "llm_credential", ["user_id"])
    op.create_index("ix_llm_credential_provider", "llm_credential", ["provider"])
    # Exactly one default per (user, provider) — a partial unique index, so the
    # database refuses a second default rather than trusting application code.
    op.create_index(
        "uq_llm_credential_default",
        "llm_credential",
        ["user_id", "provider"],
        unique=True,
        postgresql_where=sa.text("is_default"),
    )

    op.create_table(
        "llm_credential_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        # No FK: the trail must outlive the credential it describes.
        sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column("actor_ip", sa.String(length=45), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_llm_credential_audit_user_id", "llm_credential_audit", ["user_id"])
    op.create_index(
        "ix_llm_credential_audit_credential_id", "llm_credential_audit", ["credential_id"]
    )
    op.create_index("ix_llm_credential_audit_at", "llm_credential_audit", ["at"])

    # Chat sessions gain an owner. Nullable so existing rows survive the migration;
    # they become unreadable, which is correct — we cannot prove who they belong to.
    op.add_column(
        "chat_session", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column("chat_session", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column("chat_session", sa.Column("model", sa.String(length=100), nullable=True))
    op.add_column(
        "chat_session", sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_index("ix_chat_session_user_id", "chat_session", ["user_id"])
    op.create_foreign_key(
        "fk_chat_session_user", "chat_session", "app_user", ["user_id"], ["id"], ondelete="CASCADE"
    )
    op.create_foreign_key(
        "fk_chat_session_credential",
        "chat_session",
        "llm_credential",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_chat_session_credential", "chat_session", type_="foreignkey")
    op.drop_constraint("fk_chat_session_user", "chat_session", type_="foreignkey")
    op.drop_index("ix_chat_session_user_id", table_name="chat_session")
    op.drop_column("chat_session", "credential_id")
    op.drop_column("chat_session", "model")
    op.drop_column("chat_session", "provider")
    op.drop_column("chat_session", "user_id")

    op.drop_table("llm_credential_audit")
    op.drop_index("uq_llm_credential_default", table_name="llm_credential")
    op.drop_table("llm_credential")
