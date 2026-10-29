"""audit log

Revision ID: 116e7a2af170
Revises: befce6c4a656
Create Date: 2026-10-25 23:27:45.957197

Creates `audit_log` (NFR-1, DECISIONS D-23/D-24) and makes it APPEND-ONLY:
a trigger raises an exception for UPDATE, DELETE and TRUNCATE, so even a bug (or
a careless SQL session) cannot rewrite history.

The same trigger is the escape hatch for the one legitimate operation: an
operator can run `ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete`
inside a transaction to remove rows deliberately, and must enable it again.
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '116e7a2af170'
down_revision: Union[str, Sequence[str], None] = 'befce6c4a656'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRIGGER_FUNCTION = "audit_log_block_changes"
ROW_TRIGGER = "audit_log_no_update_delete"
TRUNCATE_TRIGGER = "audit_log_no_truncate"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('audit_log',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('actor_id', sa.BigInteger(), nullable=True),
    sa.Column('entity_type', sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
    sa.Column('entity_id', sa.BigInteger(), nullable=True),
    sa.Column('action', sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False),
    sa.Column('old_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('new_value', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('reason', sqlmodel.sql.sqltypes.AutoString(length=1000), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['employee.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_audit_log_actor', 'audit_log', ['actor_id', sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_audit_log_created', 'audit_log', [sa.literal_column('created_at DESC')], unique=False)
    op.create_index('ix_audit_log_entity', 'audit_log', ['entity_type', 'entity_id', sa.literal_column('created_at DESC')], unique=False)

    # Supabase: block the public Data API from this table.
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")

    # --- append-only guarantee ------------------------------------------
    op.execute(
        f"""
        CREATE FUNCTION {TRIGGER_FUNCTION}() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'audit_log is append-only: % is not allowed', TG_OP
                USING HINT = 'Drop the trigger inside a transaction if you really '
                             'need to remove rows.';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {ROW_TRIGGER}
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION {TRIGGER_FUNCTION}()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {TRUNCATE_TRIGGER}
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION {TRIGGER_FUNCTION}()
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(f"DROP TRIGGER IF EXISTS {TRUNCATE_TRIGGER} ON audit_log")
    op.execute(f"DROP TRIGGER IF EXISTS {ROW_TRIGGER} ON audit_log")
    op.execute(f"DROP FUNCTION IF EXISTS {TRIGGER_FUNCTION}()")
    op.drop_index('ix_audit_log_entity', table_name='audit_log')
    op.drop_index('ix_audit_log_created', table_name='audit_log')
    op.drop_index('ix_audit_log_actor', table_name='audit_log')
    op.drop_table('audit_log')
