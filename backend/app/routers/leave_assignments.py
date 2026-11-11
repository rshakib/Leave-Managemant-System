from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.balance_adjustment import LeaveBalanceAdjustment
from app.models.employee import Employee, Role
from app.services.assignment_rules import (
    AssignmentError,
    calculate_reassignment,
    validate_removal,
)
from app.services.audit import record
from app.models.leave_balance import (
    BulkAssignmentRequest,
    BulkAssignmentResult,
    BulkSkip,
    EmployeeLeaveType,
    LeaveAssignmentCreate,
    LeaveAssignmentTransfer,
    LeaveBalance,
    LeaveBalanceRead,
)
from app.models.leave_type import LeaveType
from app.services.locking import assert_years_open, lock_years_shared
from app.services.balances import (
    available_after,
    build_balance_reads,
    resolve_leave_year,
)

router = APIRouter(prefix="/leave-assignments", tags=["leave-assignments"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]



async def _balance_for(
    session: AsyncSession, employee_id: int, leave_type_id: int, year_id: int
) -> LeaveBalance | None:
    return await session.scalar(
        select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.leave_type_id == leave_type_id,
            LeaveBalance.leave_year_id == year_id,
        )
    )


async def _assignment_for(
    session: AsyncSession, employee_id: int, leave_type_id: int, year_id: int
) -> EmployeeLeaveType | None:
    return await session.scalar(
        select(EmployeeLeaveType).where(
            EmployeeLeaveType.employee_id == employee_id,
            EmployeeLeaveType.leave_type_id == leave_type_id,
            EmployeeLeaveType.leave_year_id == year_id,
        )
    )


def _negative_message(allocated: Decimal, balance: LeaveBalance | None) -> str:
    if balance is None:
        return f"Allocating {allocated} day(s) would make the available balance negative."
    return (
        f"Allocating {allocated} day(s) would make the available balance negative "
        f"(carried forward {balance.carried_forward}, used {balance.used}, "
        f"pending {balance.pending})."
    )


@router.post("", response_model=LeaveBalanceRead, dependencies=ADMIN_ONLY)
async def assign_leave_type(
    payload: LeaveAssignmentCreate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> LeaveBalanceRead:
    year = await resolve_leave_year(session, payload.leave_year_id)
    assert_years_open(await lock_years_shared(session, [year.id]))

    employee = await session.get(Employee, payload.employee_id)
    if employee is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Employee {payload.employee_id} not found."
        )
    if not employee.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Employee '{employee.employee_code}' is inactive and cannot be assigned leave.",
        )

    leave_type = await session.get(LeaveType, payload.leave_type_id)
    if leave_type is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Leave type {payload.leave_type_id} not found.",
        )
    if not leave_type.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Leave type '{leave_type.code}' is inactive and cannot be assigned.",
        )

    allocated = (
        payload.allocated_days
        if payload.allocated_days is not None
        else leave_type.default_quota
    )

    balance = await _balance_for(session, employee.id, leave_type.id, year.id)
    before_allocated = balance.allocated if balance is not None else None
    first_time = balance is None

    transfer = await session.scalar(
        select(LeaveAssignmentTransfer).where(
            LeaveAssignmentTransfer.employee_id == employee.id,
            LeaveAssignmentTransfer.leave_type_id == leave_type.id,
            LeaveAssignmentTransfer.leave_year_id == year.id,
        )
    )
    restored_used = Decimal("0")
    if transfer is not None and transfer.transferred_days > 0:
        al_type = await session.scalar(select(LeaveType).where(LeaveType.code == "AL"))
        if al_type is not None:
            al_balance = await session.scalar(
                select(LeaveBalance).where(
                    LeaveBalance.employee_id == employee.id,
                    LeaveBalance.leave_type_id == al_type.id,
                    LeaveBalance.leave_year_id == year.id,
                ).with_for_update()
            )
            if al_balance is not None:
                restored_used, new_al_used = calculate_reassignment(
                    transferred_days=transfer.transferred_days,
                    al_used=al_balance.used,
                )
                al_balance.used = new_al_used
            else:
                restored_used = transfer.transferred_days
        else:
            restored_used = transfer.transferred_days
        await session.delete(transfer)

    effective_used = (balance.used if balance is not None else Decimal("0")) + restored_used
    if allocated < effective_used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Allocating {allocated} day(s) is less than the {effective_used} day(s) used for this leave type.",
        )
    if available_after(balance, allocated) < 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT, _negative_message(allocated, balance)
        )

    assignment = await _assignment_for(session, employee.id, leave_type.id, year.id)
    if assignment is None:
        session.add(
            EmployeeLeaveType(
                employee_id=employee.id,
                leave_type_id=leave_type.id,
                leave_year_id=year.id,
                allocated_days=allocated,
            )
        )
    else:
        assignment.allocated_days = allocated

    if balance is None:
        balance = LeaveBalance(
            employee_id=employee.id,
            leave_type_id=leave_type.id,
            leave_year_id=year.id,
            allocated=allocated,
            used=restored_used,
        )
        session.add(balance)
    else:
        balance.allocated = allocated
        if restored_used > 0:
            balance.used = restored_used

    await session.flush()
    await session.refresh(balance)
    await record(
        session, actor.id, "leave_assignment", balance.id,
        "ASSIGN" if first_time else "REASSIGN",
        old={"allocated": before_allocated, "leave_year_id": year.id},
        new={
            "allocated": balance.allocated,
            "leave_year_id": year.id,
            "employee_code": employee.employee_code,
            "leave_type_code": leave_type.code,
        },
    )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This assignment was changed by another request at the same time. "
            "Please try again.",
        ) from None

    await session.refresh(balance)
    return (await build_balance_reads(session, [balance]))[0]


@router.delete("/{balance_id}", dependencies=ADMIN_ONLY)
async def remove_leave_assignment(
    balance_id: int,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
):
    balance = await session.get(LeaveBalance, balance_id)
    if balance is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Leave balance {balance_id} not found."
        )

    assert_years_open(await lock_years_shared(session, [balance.leave_year_id]))

    employee = await session.get(Employee, balance.employee_id)
    leave_type = await session.get(LeaveType, balance.leave_type_id)
    used_days = balance.used
    old_allocated = balance.allocated

    al_balance = None
    if balance.used > 0 and leave_type.code != "AL":
        al_type = await session.scalar(select(LeaveType).where(LeaveType.code == "AL"))
        if al_type is not None:
            al_balance = await session.scalar(
                select(LeaveBalance).where(
                    LeaveBalance.employee_id == balance.employee_id,
                    LeaveBalance.leave_type_id == al_type.id,
                    LeaveBalance.leave_year_id == balance.leave_year_id,
                ).with_for_update()
            )

    try:
        transferred_to_al = validate_removal(
            leave_type_code=leave_type.code,
            pending=balance.pending,
            used=balance.used,
            al_allocated=al_balance.allocated if al_balance else None,
            al_carried_forward=al_balance.carried_forward if al_balance else None,
            al_used=al_balance.used if al_balance else None,
            al_pending=al_balance.pending if al_balance else None,
        )
    except AssignmentError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    if transferred_to_al > 0 and al_balance is not None:
        al_balance.used += transferred_to_al

        transfer = await session.scalar(
            select(LeaveAssignmentTransfer).where(
                LeaveAssignmentTransfer.employee_id == balance.employee_id,
                LeaveAssignmentTransfer.leave_type_id == balance.leave_type_id,
                LeaveAssignmentTransfer.leave_year_id == balance.leave_year_id,
            )
        )
        if transfer is None:
            session.add(
                LeaveAssignmentTransfer(
                    employee_id=balance.employee_id,
                    leave_type_id=balance.leave_type_id,
                    leave_year_id=balance.leave_year_id,
                    transferred_days=transferred_to_al,
                )
            )
        else:
            transfer.transferred_days += transferred_to_al

    assignment = await _assignment_for(
        session, balance.employee_id, balance.leave_type_id, balance.leave_year_id
    )
    if assignment is not None:
        await session.delete(assignment)

    has_adjustments = await session.scalar(
        select(func.count())
        .select_from(LeaveBalanceAdjustment)
        .where(LeaveBalanceAdjustment.balance_id == balance.id)
    )
    if has_adjustments:
        balance.allocated = Decimal("0")
        balance.carried_forward = Decimal("0")
        balance.used = Decimal("0")
    else:
        await session.delete(balance)

    await record(
        session,
        actor.id,
        "leave_assignment",
        balance.id,
        "REMOVE",
        old={"allocated": old_allocated, "used": used_days},
        new={
            "employee_code": employee.employee_code,
            "leave_type_code": leave_type.code,
            "transferred_to_al": str(transferred_to_al),
        },
    )
    await session.commit()
    return {
        "status": "ok",
        "message": (
            f"Assignment for {leave_type.name} removed."
            + (
                f" Transferred {transferred_to_al} used day(s) to Annual Leave."
                if transferred_to_al > 0
                else ""
            )
        ),
        "transferred_to_al": str(transferred_to_al),
    }


@router.post(
    "/bulk", response_model=BulkAssignmentResult, dependencies=ADMIN_ONLY
)
async def bulk_assign(
    payload: BulkAssignmentRequest,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> BulkAssignmentResult:
    year = await resolve_leave_year(session, payload.leave_year_id)
    assert_years_open(await lock_years_shared(session, [year.id]))

    if payload.division_id is not None:
        scope = select(Employee).where(Employee.division_id == payload.division_id)
    elif payload.department_id is not None:
        scope = select(Employee).where(
            Employee.department_id == payload.department_id
        )
    else:
        scope = select(Employee).where(Employee.id.in_(payload.employee_ids or []))
    employees = (await session.scalars(scope.order_by(Employee.id))).all()

    types = (
        await session.scalars(
            select(LeaveType)
            .where(LeaveType.id.in_(payload.leave_type_ids))
            .order_by(LeaveType.code)
        )
    ).all()
    missing = set(payload.leave_type_ids) - {leave_type.id for leave_type in types}
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"Leave type(s) {sorted(missing)} not found.",
        )

    created = 0
    updated = 0
    skipped: list[BulkSkip] = []
    touched_ids: list[int] = []

    for leave_type in types:
        for employee in employees:
            if not leave_type.is_active:
                skipped.append(
                    BulkSkip(
                        employee_code=employee.employee_code,
                        leave_type_code=leave_type.code,
                        reason="leave type is inactive",
                    )
                )
                continue
            if not employee.is_active:
                skipped.append(
                    BulkSkip(
                        employee_code=employee.employee_code,
                        leave_type_code=leave_type.code,
                        reason="employee is inactive",
                    )
                )
                continue

            allocated = (
                payload.allocated_days
                if payload.allocated_days is not None
                else leave_type.default_quota
            )
            balance = await _balance_for(session, employee.id, leave_type.id, year.id)
            if available_after(balance, allocated) < 0:
                skipped.append(
                    BulkSkip(
                        employee_code=employee.employee_code,
                        leave_type_code=leave_type.code,
                        reason=(
                            f"allocating {allocated} day(s) would make the "
                            "available balance negative"
                        ),
                    )
                )
                continue

            assignment = await _assignment_for(
                session, employee.id, leave_type.id, year.id
            )
            if assignment is None:
                session.add(
                    EmployeeLeaveType(
                        employee_id=employee.id,
                        leave_type_id=leave_type.id,
                        leave_year_id=year.id,
                        allocated_days=allocated,
                    )
                )
                created += 1
            else:
                assignment.allocated_days = allocated
                updated += 1

            transfer = await session.scalar(
                select(LeaveAssignmentTransfer).where(
                    LeaveAssignmentTransfer.employee_id == employee.id,
                    LeaveAssignmentTransfer.leave_type_id == leave_type.id,
                    LeaveAssignmentTransfer.leave_year_id == year.id,
                )
            )
            restored_used = Decimal("0")
            if transfer is not None and transfer.transferred_days > 0:
                al_type = await session.scalar(select(LeaveType).where(LeaveType.code == "AL"))
                if al_type is not None:
                    al_balance = await session.scalar(
                        select(LeaveBalance).where(
                            LeaveBalance.employee_id == employee.id,
                            LeaveBalance.leave_type_id == al_type.id,
                            LeaveBalance.leave_year_id == year.id,
                        ).with_for_update()
                    )
                    if al_balance is not None:
                        restored_used, new_al_used = calculate_reassignment(
                            transferred_days=transfer.transferred_days,
                            al_used=al_balance.used,
                        )
                        al_balance.used = new_al_used
                    else:
                        restored_used = transfer.transferred_days
                else:
                    restored_used = transfer.transferred_days
                await session.delete(transfer)

            if balance is None:
                session.add(
                    LeaveBalance(
                        employee_id=employee.id,
                        leave_type_id=leave_type.id,
                        leave_year_id=year.id,
                        allocated=allocated,
                        used=restored_used,
                    )
                )
            else:
                balance.allocated = allocated
                if restored_used > 0:
                    balance.used = restored_used
            touched_ids.append(employee.id)

    await record(
        session, actor.id, "leave_assignment", None, "BULK_ASSIGN",
        new={
            "leave_year_id": year.id,
            "leave_type_ids": sorted(payload.leave_type_ids),
            "created": created,
            "updated": updated,
            "skipped": len(skipped),
            "employee_ids": touched_ids[:50],
            "employee_ids_truncated": len(touched_ids) > 50,
        },
    )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another request changed the same assignments at the same time. "
            "Nothing was saved; please try again.",
        ) from None

    return BulkAssignmentResult(
        created=created, updated=updated, skipped=len(skipped), skipped_details=skipped
    )
