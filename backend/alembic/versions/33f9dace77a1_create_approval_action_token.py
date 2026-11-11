"""create approval_action_token table

Revision ID: 33f9dace77a1
Revises: 32e8fac26002
Create Date: 2026-10-29 16:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '33f9dace77a1'
down_revision: Union[str, Sequence[str], None] = '32e8fac26002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'approval_action_token',
        sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('approval_id', sa.BigInteger(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('action', sa.String(length=20), server_default=sa.text("'APPROVE'"), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(['approval_id'], ['leave_request_approval.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_approval_action_token_hash', 'approval_action_token', ['token_hash'], unique=True)
    op.create_index('ix_approval_action_token_approval', 'approval_action_token', ['approval_id', 'expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_approval_action_token_approval', table_name='approval_action_token')
    op.drop_index('ix_approval_action_token_hash', table_name='approval_action_token')
    op.drop_table('approval_action_token')

