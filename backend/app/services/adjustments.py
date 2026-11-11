"""Manual leave-balance adjustment service."""

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

    # Lock year SHARED before balance row FOR UPDATE to preserve global lock order.
    years = await lock_years_shared(session, [balance.leave_year_id])

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
    if field not in ALLOWED_FIELDS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"'{field}' cannot be adjusted. Use one of {', '.join(ALLOWED_FIELDS)}.",
        )


def today() -> datetime.date:
    return datetime.datetime.now(datetime.timezone.utc).date()
