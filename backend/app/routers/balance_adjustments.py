import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.balance_adjustment import (
    AdjustmentCreate,
    AdjustmentPage,
    AdjustmentRead,
    LeaveBalanceAdjustment,
)
from app.models.employee import Employee, Role
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear
from app.services.adjustments import adjust, reject_unknown_field
from app.services.balances import build_balance_reads

router = APIRouter(tags=["balance-adjustments"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]


def _read_rows(rows) -> list[AdjustmentRead]:
    return [
        AdjustmentRead(
            id=row[0].id,
            created_at=row[0].created_at,
            balance_id=row[0].balance_id,
            employee_id=row[0].employee_id,
            employee_code=row[1],
            employee_name=row[2],
            leave_type_id=row[0].leave_type_id,
            leave_type_code=row[3],
            leave_type_name=row[4],
            leave_year_id=row[0].leave_year_id,
            leave_year_name=row[5],
            field=row[0].field,
            delta=row[0].delta,
            value_before=row[0].value_before,
            value_after=row[0].value_after,
            reason=row[0].reason,
            year_was_closed=row[0].year_was_closed,
            created_by=row[0].created_by,
            actor_name=row[6],
        )
        for row in rows
    ]


def _statement(filters):
    actor = aliased(Employee)
    statement = (
        select(
            LeaveBalanceAdjustment,
            Employee.employee_code,
            Employee.full_name,
            LeaveType.code,
            LeaveType.name,
            LeaveYear.name,
            actor.full_name,
        )
        .join(Employee, Employee.id == LeaveBalanceAdjustment.employee_id)
        .join(LeaveType, LeaveType.id == LeaveBalanceAdjustment.leave_type_id)
        .join(LeaveYear, LeaveYear.id == LeaveBalanceAdjustment.leave_year_id)
        .outerjoin(actor, actor.id == LeaveBalanceAdjustment.created_by)
    )
    for condition in filters:
        statement = statement.where(condition)
    return statement


@router.post(
    "/leave-balances/{balance_id}/adjust",
    response_model=dict,
    dependencies=ADMIN_ONLY,
)
async def adjust_balance(
    balance_id: int,
    payload: AdjustmentCreate,
    actor: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    reject_unknown_field((payload.field or "").upper())

    outcome = await adjust(
        session,
        balance_id,
        actor=actor,
        field=payload.field,
        delta=payload.delta,
        reason=payload.reason,
    )

    balance_read = (await build_balance_reads(session, [outcome["balance"]]))[0]
    entry = outcome["adjustment"]
    return {
        "balance": balance_read.model_dump(mode="json"),
        "adjustment": {
            "id": entry.id,
            "field": entry.field,
            "delta": str(entry.delta),
            "value_before": str(entry.value_before),
            "value_after": str(entry.value_after),
            "reason": entry.reason,
            "year_was_closed": entry.year_was_closed,
            "created_at": entry.created_at.isoformat(),
        },
        "warnings": outcome["warnings"],
    }


@router.get(
    "/leave-balance-adjustments",
    response_model=AdjustmentPage,
    dependencies=ADMIN_ONLY,
)
async def list_adjustments(
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    leave_year_id: int | None = None,
    balance_id: int | None = None,
    field: str | None = None,
    created_by: int | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> AdjustmentPage:
    limit = min(max(1, limit), 100)
    offset = max(0, offset)

    filters = []
    if balance_id is not None:
        filters.append(LeaveBalanceAdjustment.balance_id == balance_id)
    if employee_id is not None:
        filters.append(LeaveBalanceAdjustment.employee_id == employee_id)
    if leave_type_id is not None:
        filters.append(LeaveBalanceAdjustment.leave_type_id == leave_type_id)
    if leave_year_id is not None:
        filters.append(LeaveBalanceAdjustment.leave_year_id == leave_year_id)
    if field:
        filters.append(LeaveBalanceAdjustment.field == field.upper())
    if created_by is not None:
        filters.append(LeaveBalanceAdjustment.created_by == created_by)
    if date_from is not None:
        filters.append(
            LeaveBalanceAdjustment.created_at
            >= datetime.datetime.combine(date_from, datetime.time.min)
        )
    if date_to is not None:
        filters.append(
            LeaveBalanceAdjustment.created_at
            < datetime.datetime.combine(
                date_to + datetime.timedelta(days=1), datetime.time.min
            )
        )

    rows = (
        await session.execute(
            _statement(filters)
            .order_by(LeaveBalanceAdjustment.created_at.desc(), LeaveBalanceAdjustment.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = (
        await session.scalar(
            select(func.count())
            .select_from(LeaveBalanceAdjustment)
            .where(*filters)
        )
        or 0
    )
    return AdjustmentPage(
        rows=_read_rows(rows), total=total, limit=limit, offset=offset
    )


@router.get(
    "/leave-balances/me/adjustments", response_model=AdjustmentPage
)
async def my_adjustments(
    leave_year_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
    current: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AdjustmentPage:
    limit = min(max(1, limit), 100)
    offset = max(0, offset)

    filters = [LeaveBalanceAdjustment.employee_id == current.id]
    if leave_year_id is not None:
        filters.append(LeaveBalanceAdjustment.leave_year_id == leave_year_id)

    rows = (
        await session.execute(
            _statement(filters)
            .order_by(LeaveBalanceAdjustment.created_at.desc(), LeaveBalanceAdjustment.id.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    total = (
        await session.scalar(
            select(func.count())
            .select_from(LeaveBalanceAdjustment)
            .where(*filters)
        )
        or 0
    )
    return AdjustmentPage(
        rows=_read_rows(rows), total=total, limit=limit, offset=offset
    )
