"""create email outbox

Revision ID: 263a99a2d884
Revises: 92beb3d954d2
Create Date: 2026-10-25 17:39:46.311245
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '263a99a2d884'
down_revision: Union[str, Sequence[str], None] = '92beb3d954d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('email_outbox',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('event_type', sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
    sa.Column('to_emails', postgresql.ARRAY(sa.Text()), nullable=False),
    sa.Column('cc_emails', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('related_request_id', sa.BigInteger(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_attempts', sa.Integer(), server_default=sa.text('5'), nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_error', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('dedupe_key', sqlmodel.sql.sqltypes.AutoString(length=200), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.CheckConstraint("status IN ('PENDING', 'SENDING', 'SENT', 'FAILED')", name='ck_email_outbox_status'),
    sa.CheckConstraint('attempts >= 0', name='ck_email_outbox_attempts'),
    sa.ForeignKeyConstraint(['related_request_id'], ['leave_request.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('dedupe_key')
    )
    op.create_index('ix_email_outbox_due', 'email_outbox', ['status', 'next_attempt_at'], unique=False)
    op.create_index('ix_email_outbox_request', 'email_outbox', ['related_request_id'], unique=False)
    op.create_table('email_attempt',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('outbox_id', sa.BigInteger(), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('error', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True),
    sa.Column('backend', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('created_by', sa.BigInteger(), nullable=True),
    sa.ForeignKeyConstraint(['outbox_id'], ['email_outbox.id'], ),
    sa.PrimaryKeyConstraint('id')
    )

    # Supabase: block the public Data API (anon/authenticated) from these tables.
    op.execute("ALTER TABLE email_outbox ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE email_attempt ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('email_attempt')
    op.drop_index('ix_email_outbox_request', table_name='email_outbox')
    op.drop_index('ix_email_outbox_due', table_name='email_outbox')
    op.drop_table('email_outbox')
