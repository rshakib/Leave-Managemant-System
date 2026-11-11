"""create division and department

Revision ID: 9ee0f38d8146
Revises: 69d0b70a50c9
Create Date: 2026-10-23 01:27:48.922245
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9ee0f38d8146'
down_revision: Union[str, Sequence[str], None] = '69d0b70a50c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('division',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=150), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('department',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('division_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=150), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['division_id'], ['division.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('division_id', 'name', name='uq_department_division_name')
    )

    # Supabase: block the public Data API (anon/authenticated) from these tables.
    op.execute("ALTER TABLE division ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE department ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('department')
    op.drop_table('division')
