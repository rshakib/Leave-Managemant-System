"""Transactional audit logging."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.services.audit_rules import (
    limit_size,
    redact,
    to_jsonable,
    validate_entry,
)

MAX_REASON = 1000


def snapshot(instance, fields) -> dict:
    """Extract explicit fields from a model instance."""
    return {name: getattr(instance, name) for name in fields}


async def record(
    session: AsyncSession,
    actor_id: int | None,
    entity_type: str,
    entity_id: int | None,
    action: str,
    old=None,
    new=None,
    reason: str | None = None,
) -> AuditLog:
    """Write one audit row inside the caller's transaction."""
    validate_entry(entity_type, action)

    old_value = limit_size(redact(to_jsonable(old))) if old is not None else None
    new_value = limit_size(redact(to_jsonable(new))) if new is not None else None

    entry = AuditLog(
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        old_value=old_value,
        new_value=new_value,
        reason=(reason[:MAX_REASON] if reason else None),
    )
    session.add(entry)
    await session.flush()
    return entry


def balance_snapshot(balances) -> dict:
    """Capture pending, used, and available balances keyed by leave year ID."""
    return {
        str(year_id): {
            "pending": balance.pending,
            "used": balance.used,
            "available": (
                balance.allocated
                + balance.carried_forward
                - balance.used
                - balance.pending
            ),
        }
        for year_id, balance in balances.items()
    }
