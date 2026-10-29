"""add employee password_hash

Revision ID: 83a61549e9e3
Revises: 8630a284ed68
Create Date: 2026-10-25 15:00:44.385353

Adds ``employee.password_hash`` (DECISIONS D-38). The column is NOT NULL, which
is safe because the ``employee`` table was verified empty (0 rows) before this
migration ran — no backfill or default is needed.
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83a61549e9e3'
down_revision: Union[str, Sequence[str], None] = '8630a284ed68'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('employee', sa.Column('password_hash', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('employee', 'password_hash')
