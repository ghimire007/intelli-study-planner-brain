"""add campus to handbook

Revision ID: c6d7e8f9a0b1
Revises: b1f2e3d4c5a6
Create Date: 2026-05-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6d7e8f9a0b1'
down_revision: Union[str, None] = 'b1f2e3d4c5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'handbook',
        sa.Column('campus', sa.String(100), nullable=False, server_default='Wollongong'),
    )
    op.drop_constraint('uq_handbook_year_course', 'handbook', type_='unique')
    op.create_unique_constraint('uq_handbook_year_course_campus', 'handbook', ['year', 'course', 'campus'])
    op.create_index('ix_handbook_campus', 'handbook', ['campus'])


def downgrade() -> None:
    op.drop_index('ix_handbook_campus', table_name='handbook')
    op.drop_constraint('uq_handbook_year_course_campus', 'handbook', type_='unique')
    op.create_unique_constraint('uq_handbook_year_course', 'handbook', ['year', 'course'])
    op.drop_column('handbook', 'campus')
