import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.models.leave_carry_forward import (
    CarryForwardPage,
    CarryForwardRead,
    ClosingPreview,
    ClosingRequest,
    ClosingResult,
    LeaveCarryForward,
)
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear
from app.services.closing import close_year, preview

router = APIRouter(prefix="/leave-years", tags=["year-closing"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]


@router.get(
    "/{year_id}/closing-preview",
    response_model=ClosingPreview,
    dependencies=ADMIN_ONLY,
)
async def closing_preview(
    year_id: int,
    offset: int = 0,
    limit: int = 200,
    session: AsyncSession = Depends(get_session),
) -> ClosingPreview:
    return ClosingPreview(**await preview(session, year_id, offset=offset, limit=limit))


@router.post("/{year_id}/close", response_model=ClosingResult, dependencies=ADMIN_ONLY)
async def close_leave_year(
    year_id: int,
    payload: ClosingRequest,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> ClosingResult:
    return ClosingResult(
        **await close_year(
            session,
            year_id,
            actor=actor,
            confirm_name=payload.confirm_name,
            expected_fingerprint=payload.expected_fingerprint,
        )
    )


@router.get(
    "/{year_id}/carry-forwards",
    response_model=CarryForwardPage,
    dependencies=ADMIN_ONLY,
)
async def list_carry_forwards(
    year_id: int,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> CarryForwardPage:
    year = await session.get(LeaveYear, year_id)
    if year is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave year not found.")

    to_year = aliased(LeaveYear)
    closer = aliased(Employee)

    statement = (
        select(
            LeaveCarryForward,
            Employee.employee_code,
            Employee.full_name,
            LeaveType.code,
            LeaveType.name,
            LeaveYear.name,
            to_year.name,
            closer.full_name,
        )
        .join(Employee, Employee.id == LeaveCarryForward.employee_id)
        .join(LeaveType, LeaveType.id == LeaveCarryForward.leave_type_id)
        .join(LeaveYear, LeaveYear.id == LeaveCarryForward.from_leave_year_id)
        .join(to_year, to_year.id == LeaveCarryForward.to_leave_year_id)
        .outerjoin(closer, closer.id == LeaveCarryForward.processed_by)
        .where(LeaveCarryForward.from_leave_year_id == year_id)
    )
    if employee_id is not None:
        statement = statement.where(LeaveCarryForward.employee_id == employee_id)
    if leave_type_id is not None:
        statement = statement.where(LeaveCarryForward.leave_type_id == leave_type_id)

    total = await session.scalar(
        select(func.count()).select_from(statement.subquery())
    ) or 0

    rows = (
        await session.execute(
            statement.order_by(Employee.employee_code, LeaveType.code)
            .offset(max(0, offset))
            .limit(min(max(1, limit), 100))
        )
    ).all()

    return CarryForwardPage(
        rows=[
            CarryForwardRead(
                id=row[0].id,
                employee_id=row[0].employee_id,
                employee_code=row[1],
                employee_name=row[2],
                leave_type_id=row[0].leave_type_id,
                leave_type_code=row[3],
                leave_type_name=row[4],
                from_leave_year_id=row[0].from_leave_year_id,
                from_leave_year_name=row[5],
                to_leave_year_id=row[0].to_leave_year_id,
                to_leave_year_name=row[6],
                remaining_at_close=row[0].remaining_at_close,
                carried_days=row[0].carried_days,
                forfeited_days=row[0].forfeited_days,
                processed_at=row[0].processed_at,
                processed_by_name=row[7],
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
