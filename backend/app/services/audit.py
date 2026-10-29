"""Recording one audit row inside the caller's transaction (NFR-1).

Two rules:

1. **One row per business action.** Not one per field: a reader should see
   "employee 42 was updated, email changed from A to B" as a single event.

2. **FAIL CLOSED.** `record()` never commits and never swallows an error: it
   INSERTs into the caller's transaction, so if the audit row cannot be written
   the whole business action rolls back. That is the *opposite* of the email
   outbox (DECISIONS D-110), on purpose:

   * a leave decision without its email is a delayed notification — annoying,
     fixable, and the business fact (the leave is approved) is still true;
   * a leave decision without its audit row is an **unaccountable** change — the
     balance moved and nobody can say who did it. That is worse than refusing
     the change, so we refuse the change.

The failed action leaves nothing behind: no business row, no audit row, because
both live in the same transaction and are rolled back together.
"""

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
    """Take explicit fields off a model — never dump a whole ORM object.

    Dumping the object would drag in relationships, lazy loads and secret
    columns (a password hash); naming the fields keeps the audit honest.
    """
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
    """Write one audit row in the caller's transaction (never commits)."""
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
    """Small before/after picture of balances, keyed by leave year id.

    Returns Decimals; `record()` turns them into exact strings like "2.50".
    """
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
