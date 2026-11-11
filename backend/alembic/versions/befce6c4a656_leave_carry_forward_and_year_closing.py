"""leave carry forward and year closing

Revision ID: befce6c4a656
Revises: 263a99a2d884
Create Date: 2026-10-25 20:48:12.382358
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'befce6c4a656'
down_revision: Union[str, Sequence[str], None] = '263a99a2d884'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('leave_carry_forward',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('leave_type_id', sa.BigInteger(), nullable=False),
    sa.Column('from_leave_year_id', sa.BigInteger(), nullable=False),
    sa.Column('to_leave_year_id', sa.BigInteger(), nullable=False),
    sa.Column('remaining_at_close', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('carried_days', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('forfeited_days', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('processed_by', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint('carried_days >= 0', name='ck_leave_carry_forward_carried'),
    sa.CheckConstraint('forfeited_days >= 0', name='ck_leave_carry_forward_forfeited'),
    sa.CheckConstraint('from_leave_year_id <> to_leave_year_id', name='ck_leave_carry_forward_different_years'),
    sa.CheckConstraint('remaining_at_close = carried_days + forfeited_days', name='ck_leave_carry_forward_split'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ),
    sa.ForeignKeyConstraint(['from_leave_year_id'], ['leave_year.id'], ),
    sa.ForeignKeyConstraint(['leave_type_id'], ['leave_type.id'], ),
    sa.ForeignKeyConstraint(['processed_by'], ['employee.id'], ),
    sa.ForeignKeyConstraint(['to_leave_year_id'], ['leave_year.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'leave_type_id', 'from_leave_year_id', name='uq_leave_carry_forward')
    )

    op.add_column('leave_year', sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('leave_year', sa.Column('closed_by_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_leave_year_closed_by', 'leave_year', 'employee', ['closed_by_id'], ['id']
    )
    op.create_check_constraint(
        'ck_leave_year_closed_together',
        'leave_year',
        '(closed_at IS NULL) = (closed_by_id IS NULL)',
    )
    op.create_check_constraint(
        'ck_leave_year_closed_has_date',
        'leave_year',
        'NOT is_closed OR closed_at IS NOT NULL',
    )

    # Supabase: block the public Data API from the new table.
    op.execute("ALTER TABLE leave_carry_forward ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('ck_leave_year_closed_has_date', 'leave_year', type_='check')
    op.drop_constraint('ck_leave_year_closed_together', 'leave_year', type_='check')
    op.drop_constraint('fk_leave_year_closed_by', 'leave_year', type_='foreignkey')
    op.drop_column('leave_year', 'closed_by_id')
    op.drop_column('leave_year', 'closed_at')
    op.drop_table('leave_carry_forward')
