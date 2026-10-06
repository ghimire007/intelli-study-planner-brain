"""add student profile fields

Revision ID: f2a3b4c5d6e7
Revises: a1b2c3d4e5f6
"""
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def _existing_columns(table: str) -> set[str]:
    inspector = inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    existing = _existing_columns("app_user")

    if "degree_code" not in existing:
        op.add_column(
            "app_user",
            sa.Column("degree_code", sa.String(length=12), nullable=False, server_default="766"),
        )
    if "commencement_year" not in existing:
        op.add_column("app_user", sa.Column("commencement_year", sa.Integer(), nullable=True))
    if "campus" not in existing:
        op.add_column("app_user", sa.Column("campus", sa.String(length=32), nullable=True))
    if "major" not in existing:
        op.add_column("app_user", sa.Column("major", sa.String(length=120), nullable=True))
    if "elective_interests" not in existing:
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
    existing = _existing_columns("app_user")
    for column in (
        "elective_interests",
        "major",
        "campus",
        "commencement_year",
        "degree_code",
    ):
        if column in existing:
            op.drop_column("app_user", column)
