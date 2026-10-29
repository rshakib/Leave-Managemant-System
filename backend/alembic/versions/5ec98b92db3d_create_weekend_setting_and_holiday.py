"""create weekend_setting and holiday

Revision ID: 5ec98b92db3d
Revises: c4e60f6f17d8
Create Date: 2026-10-25 16:06:19.812856

Creates the weekend configuration and holiday tables (FR-CAL-1/2/3) and enables
Row Level Security on both.

Two UNIQUE quirks are handled here:
- `weekend_setting` gets TWO partial unique indexes because a plain
  `UNIQUE(employee_id)` would allow many NULL rows (D-08).
- `holiday` uses an expression index over `COALESCE(...)` because a plain
  `UNIQUE(date, division_id, department_id)` would not catch duplicates when the
  scope columns are NULL.
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5ec98b92db3d'
down_revision: Union[str, Sequence[str], None] = 'c4e60f6f17d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('holiday',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('leave_year_id', sa.BigInteger(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=150), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('division_id', sa.BigInteger(), nullable=True),
    sa.Column('department_id', sa.BigInteger(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint("type IN ('PUBLIC', 'COMPANY', 'OPTIONAL')", name='ck_holiday_type'),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], ),
    sa.ForeignKeyConstraint(['division_id'], ['division.id'], ),
    sa.ForeignKeyConstraint(['leave_year_id'], ['leave_year.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_holiday_date_scope', 'holiday', [sa.literal_column('date'), sa.literal_column('COALESCE(division_id, 0)'), sa.literal_column('COALESCE(department_id, 0)')], unique=True)
    op.create_table('weekend_setting',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=True),
    sa.Column('days_of_week', postgresql.ARRAY(sa.Integer()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint('cardinality(days_of_week) >= 1', name='ck_weekend_setting_not_empty'),
    sa.CheckConstraint('days_of_week <@ ARRAY[0, 1, 2, 3, 4, 5, 6]', name='ck_weekend_setting_range'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_weekend_setting_employee', 'weekend_setting', ['employee_id'], unique=True, postgresql_where=sa.text('employee_id IS NOT NULL'))
    op.create_index('uq_weekend_setting_single_global', 'weekend_setting', [sa.literal_column('(employee_id IS NULL)')], unique=True, postgresql_where=sa.text('employee_id IS NULL'))

    # Supabase: block the public Data API (anon/authenticated) from these tables.
    op.execute("ALTER TABLE weekend_setting ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE holiday ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_weekend_setting_single_global', table_name='weekend_setting', postgresql_where=sa.text('employee_id IS NULL'))
    op.drop_index('uq_weekend_setting_employee', table_name='weekend_setting', postgresql_where=sa.text('employee_id IS NOT NULL'))
    op.drop_table('weekend_setting')
    op.drop_index('uq_holiday_date_scope', table_name='holiday')
    op.drop_table('holiday')
