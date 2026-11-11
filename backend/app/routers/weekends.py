from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.services.audit import record
from app.models.weekend_setting import (
    WeekendSetting,
    WeekendSettingRead,
    WeekendSettingWrite,
)

router = APIRouter(prefix="/weekends", tags=["weekends"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]


async def _global_row(session: AsyncSession) -> WeekendSetting | None:
    return await session.scalar(
        select(WeekendSetting).where(WeekendSetting.employee_id.is_(None))
    )


def _to_read(
    row: WeekendSetting, employee: Employee | None = None
) -> WeekendSettingRead:
    return WeekendSettingRead(
        id=row.id,
        employee_id=row.employee_id,
        employee_name=employee.full_name if employee else None,
        employee_code=employee.employee_code if employee else None,
        days_of_week=sorted(row.days_of_week),
    )


@router.get("/global", response_model=WeekendSettingRead, dependencies=LOGGED_IN)
async def get_global_weekend(
    session: AsyncSession = Depends(get_session),
) -> WeekendSettingRead:
    row = await _global_row(session)
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Global weekend is not configured yet."
        )
    return _to_read(row)


@router.put("/global", response_model=WeekendSettingRead, dependencies=ADMIN_ONLY)
async def put_global_weekend(
    payload: WeekendSettingWrite,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> WeekendSettingRead:
    row = await _global_row(session)
    before = sorted(row.days_of_week) if row is not None else None
    if row is None:
        row = WeekendSetting(employee_id=None, days_of_week=payload.days_of_week)
        session.add(row)
    else:
        row.days_of_week = payload.days_of_week

    await session.flush()
    after = sorted(row.days_of_week)
    if before != after:
        await record(
            session, actor.id, "weekend_setting", row.id, "UPDATE",
            old={"days_of_week": before}, new={"days_of_week": after},
        )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A global weekend row already exists; please reload and try again.",
        ) from None
    await session.refresh(row)
    return _to_read(row)


@router.get(
    "/employees", response_model=list[WeekendSettingRead], dependencies=ADMIN_ONLY
)
async def list_employee_weekends(
    session: AsyncSession = Depends(get_session),
) -> list[WeekendSettingRead]:
    rows = (
        await session.scalars(
            select(WeekendSetting)
            .where(WeekendSetting.employee_id.is_not(None))
            .order_by(WeekendSetting.employee_id)
        )
    ).all()
    employees = {}
    if rows:
        employees = {
            employee.id: employee
            for employee in (
                await session.scalars(
                    select(Employee).where(
                        Employee.id.in_({row.employee_id for row in rows})
                    )
                )
            ).all()
        }
    return [_to_read(row, employees.get(row.employee_id)) for row in rows]


@router.put(
    "/employees/{employee_id}",
    response_model=WeekendSettingRead,
    dependencies=ADMIN_ONLY,
)
async def put_employee_weekend(
    employee_id: int,
    payload: WeekendSettingWrite,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> WeekendSettingRead:
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Employee {employee_id} not found."
        )

    row = await session.scalar(
        select(WeekendSetting).where(WeekendSetting.employee_id == employee_id)
    )
    before = sorted(row.days_of_week) if row is not None else None
    if row is None:
        row = WeekendSetting(employee_id=employee_id, days_of_week=payload.days_of_week)
        session.add(row)
    else:
        row.days_of_week = payload.days_of_week

    await session.flush()
    after = sorted(row.days_of_week)
    if before != after:
        await record(
            session, actor.id, "weekend_setting", row.id, "UPSERT",
            new={"employee_id": employee_id, "days_of_week": after},
            old={"days_of_week": before} if before is not None else None,
        )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That employee already has a weekend override; please reload.",
        ) from None
    await session.refresh(row)
    return _to_read(row, employee)


@router.delete(
    "/employees/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN_ONLY,
)
async def delete_employee_weekend(
    employee_id: int,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> Response:
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Employee {employee_id} not found."
        )

    row = await session.scalar(
        select(WeekendSetting).where(WeekendSetting.employee_id == employee_id)
    )
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "That employee has no weekend override to remove.",
        )

    await record(
        session, actor.id, "weekend_setting", row.id, "DELETE",
        old={"employee_id": employee_id, "days_of_week": sorted(row.days_of_week)},
    )
    await session.delete(row)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
