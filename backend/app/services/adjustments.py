"""Manual leave-balance adjustments (NFR-1).

One adjustment = one ledger row + one audit row + one balance change, all in the
caller's single transaction.

LOCK ORDER (the global one, see `services/locking.py` and `services/closing.py`):
    leave year (SHARED) -> balance row (FOR UPDATE)
We deliberately do NOT lock the employee row: `submit()` locks
year -> employee -> balance, while this path goes year -> balance, so no
transaction can ever wait for another in a circle. Because the balance row is
locked FOR UPDATE, two adjustments on the same balance are applied one after the
other (the ledger's before/after values form a chain), and an approval or a
cancellation touching the same balance serialises with us too.

Closed years ARE adjustable on purpose: the whole point is to repair history
(D-157). The year is still locked SHARED, which is what a closing takes
EXCLUSIVELY, so an adjustment and a closing can never interleave.

Deliberately NO email: FR-NOT-1 lists six events and a balance adjustment is
not one of them (D-195). The employee sees the adjustment, with its reason, on
"My balances" (GET /leave-balances/me/adjustments), and the append-only ledger
keeps it forever. Adding a seventh event would change the agreed notification
set, so it is a product decision, not an unfinished task.
"""

import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.balance_adjustment import AdjustmentField, LeaveBalanceAdjustment
from app.models.employee import Employee
from app.models.leave_balance import LeaveBalance
from app.services.adjustment_rules import (
    AdjustmentError,
    apply_adjustment,
    validate_reason,
)
from app.services.audit import balance_snapshot, record
from app.services.locking import lock_years_shared

CLOSED_YEAR_WARNING = (
    "Leave year '{name}' is closed. The adjustment was applied, but the next "
    "year's carry-forward was NOT recalculated — if the change should move days "
    "between years, make a separate CARRIED_FORWARD adjustment on the next year."
)


def _raise(error: AdjustmentError):
    raise HTTPException(error.http_status, error.message) from None


async def adjust(
    session: AsyncSession,
    balance_id: int,
    actor: Employee,
    field,
    delta,
    reason,
) -> dict:
    balance = await session.get(LeaveBalance, balance_id)
    if balance is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Leave balance {balance_id} not found. Assign the leave type to the "
            "employee for that leave year first.",
        )

    # Lock order: year SHARED first, then the balance row itself.
    years = await lock_years_shared(session, [balance.leave_year_id])

    # Re-read FRESH under the row lock (the row may have changed while we waited).
    # WITHOUT `with_for_update()` two simultaneous adjustments both read the old
    # value and one update is lost — the verification caught exactly that.
    balance = await session.scalar(
        select(LeaveBalance)
        .where(LeaveBalance.id == balance_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if balance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave balance not found.")

    try:
        result = apply_adjustment(balance, field, delta)
        cleaned_reason = validate_reason(reason)
    except AdjustmentError as error:
        _raise(error)

    year = next((row for row in years if row.id == balance.leave_year_id), None)
    year_was_closed = bool(year.is_closed) if year is not None else False

    balance.allocated = result.allocated
    balance.carried_forward = result.carried_forward
    balance.used = result.used

    entry = LeaveBalanceAdjustment(
        balance_id=balance.id,
        employee_id=balance.employee_id,
        leave_type_id=balance.leave_type_id,
        leave_year_id=balance.leave_year_id,
        field=result.field,
        delta=result.value_after - result.value_before,
        value_before=result.value_before,
        value_after=result.value_after,
        reason=cleaned_reason,
        year_was_closed=year_was_closed,
        created_by=actor.id,
    )
    session.add(entry)
    await session.flush()

    # FAIL CLOSED (D-141): the audit row is part of the fact. If it cannot be
    # written, the balance change and the ledger row roll back with it.
    await record(
        session,
        actor.id,
        "leave_balance",
        balance.id,
        "ADJUST_BALANCE",
        old={
            result.field: result.value_before,
            "available": result.available_before,
        },
        new={
            result.field: result.value_after,
            "available": result.available_after,
        },
        reason=cleaned_reason,
    )

    await session.commit()
    await session.refresh(entry)

    warnings = []
    if year_was_closed and year is not None:
        warnings.append(CLOSED_YEAR_WARNING.format(name=year.name))

    return {
        "balance": balance,
        "adjustment": entry,
        "result": result,
        "warnings": warnings,
        "balances_after": balance_snapshot({balance.leave_year_id: balance}),
    }


ALLOWED_FIELDS = tuple(item.value for item in AdjustmentField)


def reject_unknown_field(field) -> None:
    """Backstop for the router: never trust a client-supplied field name."""
    if field not in ALLOWED_FIELDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{field}' cannot be adjusted. Use one of {', '.join(ALLOWED_FIELDS)}.",
        )


def today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()
