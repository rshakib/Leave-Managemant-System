import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Index,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.services.audit_rules import changed_fields


class AuditLog(SQLModel, table=True):
    """Append-only audit trail (NFR-1, DECISIONS D-23/D-24).

    Deliberately does NOT inherit `BaseModel`: an audit row is written once and
    never changes, so the shared `updated_at` / `created_by` columns would be
    noise — and `created_by` would duplicate `actor_id`. The table is protected
    against changes by a database trigger (see the migration).
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id", text("created_at DESC")),
        Index("ix_audit_log_actor", "actor_id", text("created_at DESC")),
        Index("ix_audit_log_created", text("created_at DESC")),
    )

    id: int | None = Field(default=None, primary_key=True, sa_type=BigInteger)
    actor_id: int | None = Field(
        default=None, foreign_key="employee.id", sa_type=BigInteger, nullable=True
    )
    entity_type: str = Field(nullable=False, max_length=40)
    # Nullable: some events have no single entity (for example a report export).
    entity_id: int | None = Field(default=None, sa_type=BigInteger, nullable=True)
    action: str = Field(nullable=False, max_length=40)
    # none_as_null=True: a Python None becomes a real SQL NULL, not the JSON
    # value "null", so `old_value IS NULL` means "there was no before value".
    old_value: dict | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    new_value: dict | None = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    reason: str | None = Field(default=None, max_length=1000)
    created_at: datetime.datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), nullable=False, server_default=func.now()
        )
    )


# --- Pydantic-only models --------------------------------------------------


class AuditLogRead(SQLModel):
    id: int
    created_at: datetime.datetime
    actor_id: int | None = None
    actor_name: str | None = None
    entity_type: str
    entity_id: int | None = None
    action: str
    reason: str | None = None
    old_value: dict | None = None
    new_value: dict | None = None
    changed: list[str] = Field(default_factory=list)


class AuditLogPage(SQLModel):
    rows: list[AuditLogRead]
    total: int
    limit: int
    offset: int


def audit_read_rows(rows, names: dict[int, str]) -> list[AuditLogRead]:
    """Attach the actor name and the list of changed keys."""
    return [
        AuditLogRead(
            id=row.id,
            created_at=row.created_at,
            actor_id=row.actor_id,
            actor_name=names.get(row.actor_id),
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            action=row.action,
            reason=row.reason,
            old_value=row.old_value,
            new_value=row.new_value,
            changed=changed_fields(row.old_value, row.new_value),
        )
        for row in rows
    ]
