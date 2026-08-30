"""let a credential's secret live in infisical instead of the row

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-29
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Existing rows are all locally sealed; server_default backfills them.
    op.add_column(
        "llm_credential",
        sa.Column("backend", sa.String(length=16), nullable=False, server_default="local"),
    )
    op.add_column(
        "llm_credential", sa.Column("secret_ref", sa.String(length=128), nullable=True)
    )

    # An Infisical-backed row has no ciphertext of its own, so these stop being
    # mandatory. The CHECK below keeps "no backend holds it" from being possible.
    for column in ("key_ciphertext", "nonce", "dek_wrapped", "dek_nonce"):
        op.alter_column("llm_credential", column, existing_type=sa.LargeBinary(), nullable=True)

    op.create_check_constraint(
        "ck_llm_credential_secret_present",
        "llm_credential",
        "(backend = 'local'     AND key_ciphertext IS NOT NULL AND nonce IS NOT NULL"
        "                       AND dek_wrapped IS NOT NULL    AND dek_nonce IS NOT NULL)"
        " OR "
        "(backend = 'infisical' AND secret_ref IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_llm_credential_secret_present", "llm_credential", type_="check")
    # Rows whose secret lives in Infisical cannot satisfy the old NOT NULLs.
    op.execute("DELETE FROM llm_credential WHERE backend <> 'local'")
    for column in ("key_ciphertext", "nonce", "dek_wrapped", "dek_nonce"):
        op.alter_column("llm_credential", column, existing_type=sa.LargeBinary(), nullable=False)
    op.drop_column("llm_credential", "secret_ref")
    op.drop_column("llm_credential", "backend")
