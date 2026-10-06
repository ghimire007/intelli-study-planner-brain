"""add student profile fields

Revision ID: f2a3b4c5d6e7
Revises: a1b2c3d4e5f6
"""
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column(
        "app_user",
        sa.Column("degree_code", sa.String(length=12), nullable=False, server_default="766"),
    )
    op.add_column("app_user", sa.Column("commencement_year", sa.Integer(), nullable=True))
    op.add_column("app_user", sa.Column("campus", sa.String(length=32), nullable=True))
    op.add_column("app_user", sa.Column("major", sa.String(length=120), nullable=True))
    op.add_column(
        "app_user",
        sa.Column(
            "elective_interests",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
    )


def downgrade() -> None:
    op.drop_column("app_user", "elective_interests")
    op.drop_column("app_user", "major")
    op.drop_column("app_user", "campus")
    op.drop_column("app_user", "commencement_year")
    op.drop_column("app_user", "degree_code")
