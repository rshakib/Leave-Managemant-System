from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.services.audit import record, snapshot
from app.models.leave_balance import EmployeeLeaveType
from app.models.leave_type import (
    AccrualMode,
    LeaveType,
    LeaveTypeCreate,
    LeaveTypeRead,
    LeaveTypeUpdate,
)
from app.models.leave_year import LeaveYear

router = APIRouter(prefix="/leave-types", tags=["leave-types"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]

MONTHLY_NOT_SUPPORTED = (
    "accrual_mode 'monthly' is not supported yet; only 'fixed' is available "
    "(DECISIONS D-03)."
)


async def _get_or_404(session: AsyncSession, type_id: int) -> LeaveType:
    leave_type = await session.get(LeaveType, type_id)
    if leave_type is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave type not found.")
    return leave_type


def _reject_monthly(mode: AccrualMode) -> None:
    if mode == AccrualMode.MONTHLY:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, MONTHLY_NOT_SUPPORTED)


async def _live_allocation_count(session: AsyncSession, leave_type_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(EmployeeLeaveType)
        .join(LeaveYear, LeaveYear.id == EmployeeLeaveType.leave_year_id)
        .where(
            EmployeeLeaveType.leave_type_id == leave_type_id,
            EmployeeLeaveType.allocated_days > 0,
            LeaveYear.is_closed.is_(False),
        )
    )
    return count or 0


async def _ensure_code_free(
    session: AsyncSession, code: str, exclude_id: int | None = None
) -> None:
    statement = select(LeaveType).where(LeaveType.code == code)
    if exclude_id is not None:
        statement = statement.where(LeaveType.id != exclude_id)
    if await session.scalar(statement.limit(1)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A leave type with code '{code}' already exists."
        )


async def _ensure_name_free(
    session: AsyncSession, name: str, exclude_id: int | None = None
) -> None:
    statement = select(LeaveType).where(LeaveType.name == name)
    if exclude_id is not None:
        statement = statement.where(LeaveType.id != exclude_id)
    if await session.scalar(statement.limit(1)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A leave type named '{name}' already exists."
        )


@router.post(
    "",
    response_model=LeaveTypeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN_ONLY,
)
async def create_leave_type(
    payload: LeaveTypeCreate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> LeaveTypeRead:
    _reject_monthly(payload.accrual_mode)
    await _ensure_code_free(session, payload.code)
    await _ensure_name_free(session, payload.name)

    data = payload.model_dump()
    if not data["carry_forward_allowed"]:
        data["max_carry_forward_days"] = Decimal("0")

    leave_type = LeaveType(**data)
    session.add(leave_type)
    await session.flush()
    await record(
        session, actor.id, "leave_type", leave_type.id, "CREATE",
        new=snapshot(leave_type, ("code", "name", "default_quota",
                                 "carry_forward_allowed", "max_carry_forward_days",
                                 "is_active")),
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A leave type with that code or name already exists.",
        ) from None
    await session.refresh(leave_type)
    return LeaveTypeRead.model_validate(leave_type)


@router.get("", response_model=list[LeaveTypeRead], dependencies=LOGGED_IN)
async def list_leave_types(
    session: AsyncSession = Depends(get_session),
) -> list[LeaveTypeRead]:
    result = await session.scalars(select(LeaveType).order_by(LeaveType.code))
    return [LeaveTypeRead.model_validate(t) for t in result.all()]


@router.get("/{type_id}", response_model=LeaveTypeRead, dependencies=LOGGED_IN)
async def get_leave_type(
    type_id: int,
    session: AsyncSession = Depends(get_session),
) -> LeaveTypeRead:
    leave_type = await _get_or_404(session, type_id)
    return LeaveTypeRead.model_validate(leave_type)


@router.patch("/{type_id}", response_model=LeaveTypeRead, dependencies=ADMIN_ONLY)
async def update_leave_type(
    type_id: int,
    payload: LeaveTypeUpdate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> LeaveTypeRead:
    leave_type = await _get_or_404(session, type_id)
    data = payload.model_dump(exclude_unset=True)
    before = snapshot(leave_type, ("code", "name", "default_quota",
                                   "carry_forward_allowed", "max_carry_forward_days",
                                   "is_active"))

    if "accrual_mode" in data:
        _reject_monthly(data["accrual_mode"])

    if "code" in data and data["code"] != leave_type.code:
        await _ensure_code_free(session, data["code"], exclude_id=type_id)
    if "name" in data and data["name"] != leave_type.name:
        await _ensure_name_free(session, data["name"], exclude_id=type_id)

    if data.get("is_active") is False and leave_type.is_active:
        live = await _live_allocation_count(session, type_id)
        if live:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot deactivate leave type '{leave_type.code}': it is still "
                f"allocated to {live} employee(s) in an open leave year. Set those "
                "allocations to 0 days first, or wait until the leave year is closed.",
            )

    carry_forward = data.get("carry_forward_allowed", leave_type.carry_forward_allowed)
    if not carry_forward:
        data["max_carry_forward_days"] = Decimal("0")

    for field, value in data.items():
        setattr(leave_type, field, value)

    after = snapshot(leave_type, ("code", "name", "default_quota",
                                  "carry_forward_allowed", "max_carry_forward_days",
                                  "is_active"))
    if before != after:
        action = "UPDATE"
        if before["is_active"] and not after["is_active"]:
            action = "DEACTIVATE"
        elif not before["is_active"] and after["is_active"]:
            action = "ACTIVATE"
        await record(session, actor.id, "leave_type", leave_type.id, action,
                     old=before, new=after)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A leave type with that code or name already exists.",
        ) from None
    await session.refresh(leave_type)
    return LeaveTypeRead.model_validate(leave_type)
