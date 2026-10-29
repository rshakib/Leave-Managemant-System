from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.models.leave_balance import LeaveBalance, LeaveBalanceRead
from app.services.balances import build_balance_reads, find_active_leave_year

router = APIRouter(prefix="/leave-balances", tags=["leave-balances"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]


@router.get("", response_model=list[LeaveBalanceRead], dependencies=ADMIN_ONLY)
async def list_leave_balances(
    employee_id: int | None = None,
    division_id: int | None = None,
    department_id: int | None = None,
    leave_type_id: int | None = None,
    leave_year_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[LeaveBalanceRead]:
    """All balances, filtered. Defaults to the active leave year."""
    if leave_year_id is None:
        year = await find_active_leave_year(session)
        if year is None:
            return []
        leave_year_id = year.id

    statement = select(LeaveBalance).where(
        LeaveBalance.leave_year_id == leave_year_id
    )
    if employee_id is not None:
        statement = statement.where(LeaveBalance.employee_id == employee_id)
    if leave_type_id is not None:
        statement = statement.where(LeaveBalance.leave_type_id == leave_type_id)
    if division_id is not None or department_id is not None:
        statement = statement.join(
            Employee, Employee.id == LeaveBalance.employee_id
        )
        if division_id is not None:
            statement = statement.where(Employee.division_id == division_id)
        if department_id is not None:
            statement = statement.where(Employee.department_id == department_id)

    balances = (await session.scalars(statement.order_by(LeaveBalance.id))).all()
    return await build_balance_reads(session, list(balances))


@router.get("/me", response_model=list[LeaveBalanceRead], dependencies=LOGGED_IN)
async def my_leave_balances(
    leave_year_id: int | None = None,
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[LeaveBalanceRead]:
    """The signed-in user's own balances for the active year (or a given one).

    The query is hard-filtered by the current employee's id, so no other
    employee's rows are ever reachable from here.
    """
    if leave_year_id is None:
        year = await find_active_leave_year(session)
        if year is None:
            return []
        leave_year_id = year.id

    balances = (
        await session.scalars(
            select(LeaveBalance)
            .where(
                LeaveBalance.employee_id == employee.id,
                LeaveBalance.leave_year_id == leave_year_id,
            )
            .order_by(LeaveBalance.id)
        )
    ).all()
    return await build_balance_reads(session, list(balances))
