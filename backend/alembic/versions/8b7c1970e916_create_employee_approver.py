"""create employee_approver

Revision ID: 8b7c1970e916
Revises: 5ec98b92db3d
Create Date: 2026-10-25 16:23:59.497796
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b7c1970e916'
down_revision: Union[str, Sequence[str], None] = '5ec98b92db3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('employee_approver',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('employee_id', sa.BigInteger(), nullable=False),
    sa.Column('approver_id', sa.BigInteger(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint('employee_id <> approver_id', name='ck_employee_approver_not_self'),
    sa.ForeignKeyConstraint(['approver_id'], ['employee.id'], ),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'approver_id', name='uq_employee_approver')
    )

    op.execute("ALTER TABLE employee_approver ENABLE ROW LEVEL SECURITY")

    connection = op.get_bind()
    pending = connection.execute(
        sa.text(
            "SELECT count(*) FROM employee "
            "WHERE supervisor_id IS NOT NULL AND is_active = true"
        )
    ).scalar()

    if pending:
        connection.execute(
            sa.text(
                "INSERT INTO employee_approver (employee_id, approver_id, is_active) "
                "SELECT e.id, e.supervisor_id, true FROM employee e "
                "WHERE e.supervisor_id IS NOT NULL AND e.is_active = true "
                "AND NOT EXISTS (SELECT 1 FROM employee_approver ea "
                "                WHERE ea.employee_id = e.id "
                "                  AND ea.approver_id = e.supervisor_id)"
            )
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('employee_approver')
