"""merge authentication and planner migration heads

Revision ID: f8a9b0c1d2e3
Revises: c2d3e4f5a6b7, e7a8b9c0d1e2
Create Date: 2026-07-28
"""

from typing import Sequence, Union


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, tuple[str, str], None] = (
    "c2d3e4f5a6b7",
    "e7a8b9c0d1e2",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
