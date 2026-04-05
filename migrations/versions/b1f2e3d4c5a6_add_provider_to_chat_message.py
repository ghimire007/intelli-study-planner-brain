"""add provider to chat_message

Revision ID: b1f2e3d4c5a6
Revises: a3cc517d783b
Create Date: 2026-04-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1f2e3d4c5a6'
down_revision: Union[str, None] = 'a3cc517d783b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE llmprovider AS ENUM ('gemini', 'anthropic', 'openai')")
    op.add_column(
        'chat_message',
        sa.Column('provider', sa.Enum('gemini', 'anthropic', 'openai', name='llmprovider'), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('chat_message', 'provider')
    op.execute("DROP TYPE llmprovider")
