"""add authentication tables

Revision ID: c2d3e4f5a6b7
Revises: b1f2e3d4c5a6
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1f2e3d4c5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_user",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=100), nullable=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_app_user_email", "app_user", ["email"], unique=True)
    op.create_table(
        "auth_session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_auth_session_expires_at", "auth_session", ["expires_at"], unique=False
    )
    op.create_index(
        "ix_auth_session_token_hash", "auth_session", ["token_hash"], unique=True
    )
    op.create_index(
        "ix_auth_session_user_id", "auth_session", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_auth_session_user_id", table_name="auth_session")
    op.drop_index("ix_auth_session_token_hash", table_name="auth_session")
    op.drop_index("ix_auth_session_expires_at", table_name="auth_session")
    op.drop_table("auth_session")
    op.drop_index("ix_app_user_email", table_name="app_user")
    op.drop_table("app_user")
