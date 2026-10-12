"""add elective mode to user

Revision ID: 47293dc235ea
Revises: f2a3b4c5d6e7
Create Date: 2026-10-11 15:57:50.198836

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '47293dc235ea'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('app_user', sa.Column('elective_mode', sa.String(length=20), server_default='degree', nullable=False))

def downgrade() -> None:
    op.drop_column('app_user', 'elective_mode')
