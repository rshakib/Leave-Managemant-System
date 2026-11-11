"""create employee and employee_role

Revision ID: 8630a284ed68
Revises: 9ee0f38d8146
Create Date: 2026-10-23 01:33:00.388830
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8630a284ed68'
down_revision: Union[str, Sequence[str], None] = '9ee0f38d8146'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('employee',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('employee_code', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('full_name', sqlmodel.sql.sqltypes.AutoString(length=150), nullable=False),
    sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
    sa.Column('phone', sqlmodel.sql.sqltypes.AutoString(length=30), nullable=True),
    sa.Column('designation', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=True),
    sa.Column('division_id', sa.BigInteger(), nullable=False),
    sa.Column('department_id', sa.BigInteger(), nullable=False),
    sa.Column('supervisor_id', sa.BigInteger(), nullable=True),
    sa.Column('joining_date', sa.Date(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['department_id'], ['department.id'], ),
    sa.ForeignKeyConstraint(['division_id'], ['division.id'], ),
    sa.ForeignKeyConstraint(['supervisor_id'], ['employee.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('employee_code')
    )
    op.create_table('employee_role',
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.CheckConstraint("role IN ('ADMIN', 'EMPLOYEE', 'APPROVER')", name='ck_employee_role_role'),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ),
    sa.PrimaryKeyConstraint('employee_id', 'role', name='pk_employee_role')
    )

    # Supabase: block the public Data API (anon/authenticated) from these tables.
    op.execute("ALTER TABLE employee ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE employee_role ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('employee_role')
    op.drop_table('employee')
