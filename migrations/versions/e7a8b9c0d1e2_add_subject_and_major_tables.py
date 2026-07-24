"""add subject and major tables

Revision ID: e7a8b9c0d1e2
Revises: d1e2f3a4b5c6
Create Date: 2026-07-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7a8b9c0d1e2'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _kb_table(name: str, uq_name: str) -> None:
    op.create_table(
        name,
        sa.Column('id', sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column('year', sa.Integer(), nullable=False, index=True),
        sa.Column('code', sa.String(length=20), nullable=False, index=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('credit_points', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=255), nullable=False),
        sa.Column('card', sa.Text(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.UniqueConstraint('year', 'code', name=uq_name),
    )


def upgrade() -> None:
    _kb_table('subject', 'uq_subject_year_code')
    _kb_table('major', 'uq_major_year_code')


def downgrade() -> None:
    op.drop_table('major')
    op.drop_table('subject')
