"""create leave_year and leave_type

Revision ID: 8e050ee9b800
Revises: 83a61549e9e3
Create Date: 2026-10-25 15:34:53.014401

Creates the `leave_year` and `leave_type` tables (FR-LT-1) and enables Row Level
Security on both, as in Phases 2-3.

`leave_year` gets a PARTIAL UNIQUE INDEX on `is_active` so at most one year can
be active at a time (DECISIONS D-14 / D-52), plus a CHECK that
`end_date >= start_date`.
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e050ee9b800'
down_revision: Union[str, Sequence[str], None] = '83a61549e9e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('leave_type',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('default_quota', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('accrual_mode', sa.String(length=20), server_default=sa.text("'fixed'"), nullable=False),
    sa.Column('allow_half_day', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('require_attachment_after_days', sa.Integer(), nullable=True),
    sa.Column('carry_forward_allowed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('max_carry_forward_days', sa.Numeric(precision=5, scale=2), server_default=sa.text('0'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint("accrual_mode IN ('fixed', 'monthly')", name='ck_leave_type_accrual_mode'),
    sa.CheckConstraint('default_quota >= 0', name='ck_leave_type_default_quota'),
    sa.CheckConstraint('max_carry_forward_days >= 0', name='ck_leave_type_max_carry_forward'),
    sa.CheckConstraint('require_attachment_after_days IS NULL OR require_attachment_after_days > 0', name='ck_leave_type_attachment_days'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    sa.UniqueConstraint('name')
    )
    op.create_table('leave_year',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
    sa.Column('start_date', sa.Date(), nullable=False),
    sa.Column('end_date', sa.Date(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('is_closed', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint('end_date >= start_date', name='ck_leave_year_date_order'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_index('uq_leave_year_single_active', 'leave_year', ['is_active'], unique=True, postgresql_where=sa.text('is_active'))

    # Supabase: block the public Data API (anon/authenticated) from these tables.
    op.execute("ALTER TABLE leave_year ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE leave_type ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_leave_year_single_active', table_name='leave_year', postgresql_where=sa.text('is_active'))
    op.drop_table('leave_year')
    op.drop_table('leave_type')
