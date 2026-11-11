"""add leave request cancellation

Revision ID: 92beb3d954d2
Revises: ead5bf61ec76
Create Date: 2026-10-25 17:20:14.984395
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92beb3d954d2'
down_revision: Union[str, Sequence[str], None] = 'ead5bf61ec76'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('leave_request', sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('leave_request', sa.Column('cancelled_by_id', sa.BigInteger(), nullable=True))
    op.add_column('leave_request', sa.Column('cancel_reason', sa.Text(), nullable=True))
    op.create_foreign_key(
        'fk_leave_request_cancelled_by',
        'leave_request',
        'employee',
        ['cancelled_by_id'],
        ['id'],
    )
    op.create_check_constraint(
        'ck_leave_request_cancelled_pair',
        'leave_request',
        "(cancelled_at IS NULL AND cancelled_by_id IS NULL) OR "
        "(cancelled_at IS NOT NULL AND cancelled_by_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'ck_leave_request_cancelled_pair', 'leave_request', type_='check'
    )
    op.drop_constraint(
        'fk_leave_request_cancelled_by', 'leave_request', type_='foreignkey'
    )
    op.drop_column('leave_request', 'cancel_reason')
    op.drop_column('leave_request', 'cancelled_by_id')
    op.drop_column('leave_request', 'cancelled_at')
