"""create leave_request tables

Revision ID: ead5bf61ec76
Revises: 8b7c1970e916
Create Date: 2026-10-25 16:33:22.158067
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ead5bf61ec76'
down_revision: Union[str, Sequence[str], None] = '8b7c1970e916'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('leave_request',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('leave_type_id', sa.BigInteger(), nullable=False),
    sa.Column('leave_year_id', sa.BigInteger(), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('day_type', sa.String(length=20), server_default=sa.text("'FULL_DAY'"), nullable=False),
    sa.Column('chargeable_days', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('attachment_url', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('final_decided_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint("day_type = 'FULL_DAY' OR start_date = end_date", name='ck_leave_request_half_day_single'),
    sa.CheckConstraint("day_type IN ('FULL_DAY', 'FIRST_HALF', 'SECOND_HALF')", name='ck_leave_request_day_type'),
    sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')", name='ck_leave_request_status'),
    sa.CheckConstraint('chargeable_days > 0', name='ck_leave_request_days'),
    sa.CheckConstraint('start_date <= end_date', name='ck_leave_request_dates'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ),
    sa.ForeignKeyConstraint(['leave_type_id'], ['leave_type.id'], ),
    sa.ForeignKeyConstraint(['leave_year_id'], ['leave_year.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_leave_request_employee_dates', 'leave_request', ['employee_id', 'start_date', 'end_date'], unique=False)
    op.create_index('ix_leave_request_employee_status', 'leave_request', ['employee_id', 'status'], unique=False)
    op.create_table('leave_request_allocation',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('leave_request_id', sa.BigInteger(), nullable=False),
    sa.Column('leave_year_id', sa.BigInteger(), nullable=False),
    sa.Column('days', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint('days > 0', name='ck_leave_request_allocation_days'),
    sa.ForeignKeyConstraint(['leave_request_id'], ['leave_request.id'], ),
    sa.ForeignKeyConstraint(['leave_year_id'], ['leave_year.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('leave_request_id', 'leave_year_id', name='uq_leave_request_allocation')
    )
    op.create_table('leave_request_approval',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('leave_request_id', sa.BigInteger(), nullable=False),
    sa.Column('approver_id', sa.BigInteger(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('acted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'SKIPPED')", name='ck_leave_request_approval_status'),
    sa.ForeignKeyConstraint(['approver_id'], ['employee.id'], ),
    sa.ForeignKeyConstraint(['leave_request_id'], ['leave_request.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('leave_request_id', 'approver_id', name='uq_leave_request_approval')
    )
    op.create_index('ix_leave_request_approval_approver_status', 'leave_request_approval', ['approver_id', 'status'], unique=False)

    # Supabase: block the public Data API (anon/authenticated) from these tables.
    op.execute("ALTER TABLE leave_request ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leave_request_allocation ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leave_request_approval ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_leave_request_approval_approver_status', table_name='leave_request_approval')
    op.drop_table('leave_request_approval')
    op.drop_table('leave_request_allocation')
    op.drop_index('ix_leave_request_employee_status', table_name='leave_request')
    op.drop_index('ix_leave_request_employee_dates', table_name='leave_request')
    op.drop_table('leave_request')
