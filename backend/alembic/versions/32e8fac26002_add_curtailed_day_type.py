"""add curtailed_day_type to leave_curtailment

Revision ID: 32e8fac26002
Revises: 31d7fec15001
Create Date: 2026-10-29 13:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32e8fac26002'
down_revision: Union[str, Sequence[str], None] = '31d7fec15001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'leave_curtailment',
        sa.Column('curtailed_day_type', sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('leave_curtailment', 'curtailed_day_type')
