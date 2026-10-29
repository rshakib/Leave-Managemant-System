"""create employee_leave_type and leave_balance

Revision ID: c4e60f6f17d8
Revises: 8e050ee9b800
Create Date: 2026-10-25 15:52:16.773467

Creates the leave-type assignment and balance tables (FR-LT-2, FR-LT-3) and
enables Row Level Security on both, as in earlier phases.

Notes:
- `leave_balance.carried_forward` follows DECISIONS D-02 (not the schema's
  `carried_in`).
- `ck_leave_balance_available_not_negative` is the database-level guarantee
  that `allocated + carried_forward - used - pending` is never negative.
- `available` is NOT a column: it is computed in the API's Read model.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e60f6f17d8'
down_revision: Union[str, Sequence[str], None] = '8e050ee9b800'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('employee_leave_type',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('leave_type_id', sa.BigInteger(), nullable=False),
    sa.Column('leave_year_id', sa.BigInteger(), nullable=False),
    sa.Column('allocated_days', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint('allocated_days >= 0', name='ck_employee_leave_type_days'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ),
    sa.ForeignKeyConstraint(['leave_type_id'], ['leave_type.id'], ),
    sa.ForeignKeyConstraint(['leave_year_id'], ['leave_year.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'leave_type_id', 'leave_year_id', name='uq_employee_leave_type')
    )
    op.create_table('leave_balance',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('leave_type_id', sa.BigInteger(), nullable=False),
    sa.Column('leave_year_id', sa.BigInteger(), nullable=False),
    sa.Column('allocated', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('carried_forward', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('used', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('pending', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint('allocated + carried_forward - used - pending >= 0', name='ck_leave_balance_available_not_negative'),
    sa.CheckConstraint('allocated >= 0', name='ck_leave_balance_allocated'),
    sa.CheckConstraint('carried_forward >= 0', name='ck_leave_balance_carried'),
    sa.CheckConstraint('pending >= 0', name='ck_leave_balance_pending'),
    sa.CheckConstraint('used >= 0', name='ck_leave_balance_used'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ),
    sa.ForeignKeyConstraint(['leave_type_id'], ['leave_type.id'], ),
    sa.ForeignKeyConstraint(['leave_year_id'], ['leave_year.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'leave_type_id', 'leave_year_id', name='uq_leave_balance')
    )

    # Supabase: block the public Data API (anon/authenticated) from these tables.
    op.execute("ALTER TABLE employee_leave_type ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leave_balance ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('leave_balance')
    op.drop_table('employee_leave_type')
