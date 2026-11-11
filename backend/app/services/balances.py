"""Leave balance helpers."""

from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.leave_balance import LeaveBalance, LeaveBalanceRead
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear

NO_ACTIVE_YEAR = (
    "There is no active leave year. Activate one on the Leave years page "
    "before assigning or viewing balances."
)


async def find_active_leave_year(session: AsyncSession) -> LeaveYear | None:
    return await session.scalar(
        select(LeaveYear).where(LeaveYear.is_active.is_(True)).limit(1)
    )


async def resolve_leave_year(
    session: AsyncSession, leave_year_id: int | None
) -> LeaveYear:
    """Return the requested or active open leave year."""
    if leave_year_id is None:
        year = await find_active_leave_year(session)
        if year is None:
            raise HTTPException(status.HTTP_409_CONFLICT, NO_ACTIVE_YEAR)
    else:
        year = await session.get(LeaveYear, leave_year_id)
        if year is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Leave year {leave_year_id} not found."
            )

    if year.is_closed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Leave year '{year.name}' is closed and cannot be changed.",
        )
    return year


def available_of(balance: LeaveBalance) -> Decimal:
    return (
        balance.allocated + balance.carried_forward - balance.used - balance.pending
    )


def available_after(balance: LeaveBalance | None, allocated: Decimal) -> Decimal:
    if balance is None:
        return allocated
    return (
        allocated + balance.carried_forward - balance.used - balance.pending
    )


async def build_balance_reads(
    session: AsyncSession, balances: list[LeaveBalance]
) -> list[LeaveBalanceRead]:
    """Attach employee, leave type, and leave year metadata with computed availability."""
    if not balances:
        return []

    employees = {
        employee.id: employee
        for employee in (
            await session.scalars(
                select(Employee).where(
                    Employee.id.in_({b.employee_id for b in balances})
                )
            )
        ).all()
    }
    leave_types = {
        leave_type.id: leave_type
        for leave_type in (
            await session.scalars(
                select(LeaveType).where(
                    LeaveType.id.in_({b.leave_type_id for b in balances})
                )
            )
        ).all()
    }
    years = {
        year.id: year
        for year in (
            await session.scalars(
                select(LeaveYear).where(
                    LeaveYear.id.in_({b.leave_year_id for b in balances})
                )
            )
        ).all()
    }

    return [
        LeaveBalanceRead(
            id=balance.id,
            employee_id=balance.employee_id,
            employee_name=employees[balance.employee_id].full_name,
            employee_code=employees[balance.employee_id].employee_code,
            leave_type_id=balance.leave_type_id,
            leave_type_code=leave_types[balance.leave_type_id].code,
            leave_type_name=leave_types[balance.leave_type_id].name,
            leave_year_id=balance.leave_year_id,
            leave_year_name=years[balance.leave_year_id].name,
            allocated=balance.allocated,
            carried_forward=balance.carried_forward,
            used=balance.used,
            pending=balance.pending,
            available=available_of(balance),
        )
        for balance in balances
    ]
