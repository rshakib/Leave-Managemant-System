import datetime
from decimal import Decimal
import zoneinfo
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.core.config import settings
from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.models.leave_balance import LeaveBalance, LeaveBalanceRead
from app.services.balances import build_balance_reads, find_active_leave_year

router = APIRouter(prefix="/leave-balances", tags=["leave-balances"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]


class TeamMemberLeaveEvent(SQLModel):
    request_id: int
    employee_id: int
    employee_name: str
    employee_code: str
    leave_type_code: str
    leave_type_name: str
    start_date: datetime.date
    end_date: datetime.date
    chargeable_days: Decimal


class TeamOverviewStats(SQLModel):
    subordinates_count: int
    on_leave_today_count: int
    on_leave_today: list[TeamMemberLeaveEvent]
    upcoming_leaves_count: int
    upcoming_leaves: list[TeamMemberLeaveEvent]
    pending_approvals_count: int


async def _get_subordinate_ids(session: AsyncSession, employee: Employee) -> set[int]:
    sub_query = select(Employee.id).where(
        Employee.supervisor_id == employee.id,
        Employee.is_active.is_(True),
    )
    return set((await session.scalars(sub_query)).all())


@router.get("", response_model=list[LeaveBalanceRead], dependencies=ADMIN_ONLY)
async def list_leave_balances(
    employee_id: int | None = None,
    division_id: int | None = None,
    department_id: int | None = None,
    leave_type_id: int | None = None,
    leave_year_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[LeaveBalanceRead]:
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


@router.get("/team", response_model=list[LeaveBalanceRead], dependencies=LOGGED_IN)
async def team_leave_balances(
    leave_year_id: int | None = None,
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[LeaveBalanceRead]:
    if leave_year_id is None:
        year = await find_active_leave_year(session)
        if year is None:
            return []
        leave_year_id = year.id

    all_sub_ids = await _get_subordinate_ids(session, employee)
    if not all_sub_ids:
        return []

    statement = (
        select(LeaveBalance)
        .where(
            LeaveBalance.employee_id.in_(all_sub_ids),
            LeaveBalance.leave_year_id == leave_year_id,
        )
        .order_by(LeaveBalance.employee_id, LeaveBalance.leave_type_id)
    )

    balances = (await session.scalars(statement)).all()
    return await build_balance_reads(session, list(balances))


@router.get("/team/stats", response_model=TeamOverviewStats, dependencies=LOGGED_IN)
async def team_leave_stats(
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TeamOverviewStats:
    from app.models.leave_request import LeaveRequest, RequestStatus
    from app.models.leave_type import LeaveType

    all_sub_ids = await _get_subordinate_ids(session, employee)
    if not all_sub_ids:
        return TeamOverviewStats(
            subordinates_count=0,
            on_leave_today_count=0,
            on_leave_today=[],
            upcoming_leaves_count=0,
            upcoming_leaves=[],
            pending_approvals_count=0,
        )

    today = datetime.datetime.now(zoneinfo.ZoneInfo(settings.org_timezone)).date()
    next_7_days = today + datetime.timedelta(days=7)

    today_stmt = (
        select(LeaveRequest, Employee, LeaveType)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .where(
            LeaveRequest.employee_id.in_(all_sub_ids),
            LeaveRequest.status == RequestStatus.APPROVED,
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today,
        )
        .order_by(LeaveRequest.start_date)
    )
    today_rows = (await session.execute(today_stmt)).all()
    on_leave_today = [
        TeamMemberLeaveEvent(
            request_id=req.id,
            employee_id=emp.id,
            employee_name=emp.full_name,
            employee_code=emp.employee_code,
            leave_type_code=lt.code,
            leave_type_name=lt.name,
            start_date=req.start_date,
            end_date=req.end_date,
            chargeable_days=req.chargeable_days,
        )
        for req, emp, lt in today_rows
    ]

    up_stmt = (
        select(LeaveRequest, Employee, LeaveType)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .where(
            LeaveRequest.employee_id.in_(all_sub_ids),
            LeaveRequest.status == RequestStatus.APPROVED,
            LeaveRequest.start_date > today,
            LeaveRequest.start_date <= next_7_days,
        )
        .order_by(LeaveRequest.start_date)
    )
    up_rows = (await session.execute(up_stmt)).all()
    upcoming_leaves = [
        TeamMemberLeaveEvent(
            request_id=req.id,
            employee_id=emp.id,
            employee_name=emp.full_name,
            employee_code=emp.employee_code,
            leave_type_code=lt.code,
            leave_type_name=lt.name,
            start_date=req.start_date,
            end_date=req.end_date,
            chargeable_days=req.chargeable_days,
        )
        for req, emp, lt in up_rows
    ]

    pending_stmt = select(func.count(LeaveRequest.id)).where(
        LeaveRequest.employee_id.in_(all_sub_ids),
        LeaveRequest.status == RequestStatus.PENDING,
    )
    pending_count = (await session.execute(pending_stmt)).scalar() or 0

    return TeamOverviewStats(
        subordinates_count=len(all_sub_ids),
        on_leave_today_count=len(on_leave_today),
        on_leave_today=on_leave_today,
        upcoming_leaves_count=len(upcoming_leaves),
        upcoming_leaves=upcoming_leaves,
        pending_approvals_count=int(pending_count),
    )


@router.get("/me", response_model=list[LeaveBalanceRead], dependencies=LOGGED_IN)
async def my_leave_balances(
    leave_year_id: int | None = None,
    employee: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[LeaveBalanceRead]:
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
