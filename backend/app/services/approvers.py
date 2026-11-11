"""Employee approver assignment rules."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee, EmployeeRole, Role
from app.models.employee_approver import ApproverRead, EmployeeApprover
from app.services.audit import record
from app.models.leave_request import (
    ApprovalStatus,
    LeaveRequest,
    LeaveRequestApproval,
    RequestStatus,
)

MAX_APPROVERS = 10


async def approver_role_holders(
    session: AsyncSession, employee_ids: list[int]
) -> set[int]:
    if not employee_ids:
        return set()
    rows = (
        await session.scalars(
            select(EmployeeRole).where(
                EmployeeRole.employee_id.in_(employee_ids),
                EmployeeRole.role == Role.APPROVER,
            )
        )
    ).all()
    return {row.employee_id for row in rows}


def require_approver_role(approvers, holders: set[int]) -> None:
    """Ensure every assigned approver already holds the APPROVER role."""
    missing = [
        approver.employee_code for approver in approvers if approver.id not in holders
    ]
    if missing:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "These employees do not have the APPROVER role: "
            f"{', '.join(missing)}. Give them the approver role on the Employees "
            "page first, then assign them here.",
        )


async def active_approver_rows(
    session: AsyncSession, employee_id: int
) -> list[EmployeeApprover]:
    return list(
        (
            await session.scalars(
                select(EmployeeApprover)
                .where(
                    EmployeeApprover.employee_id == employee_id,
                    EmployeeApprover.is_active.is_(True),
                )
                .order_by(EmployeeApprover.approver_id)
            )
        ).all()
    )


async def approver_reads(
    session: AsyncSession, employee_id: int
) -> list[ApproverRead]:
    rows = await active_approver_rows(session, employee_id)
    if not rows:
        return []

    employee = await session.get(Employee, employee_id)
    supervisor_id = employee.supervisor_id if employee else None

    people = {
        person.id: person
        for person in (
            await session.scalars(
                select(Employee).where(
                    Employee.id.in_({row.approver_id for row in rows})
                )
            )
        ).all()
    }
    return [
        ApproverRead(
            id=row.approver_id,
            employee_code=people[row.approver_id].employee_code,
            full_name=people[row.approver_id].full_name,
            is_supervisor=(row.approver_id == supervisor_id),
        )
        for row in rows
        if row.approver_id in people
    ]


async def active_approver_count_for_others(
    session: AsyncSession, employee_id: int
) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(EmployeeApprover)
        .join(Employee, Employee.id == EmployeeApprover.employee_id)
        .where(
            EmployeeApprover.approver_id == employee_id,
            EmployeeApprover.is_active.is_(True),
            Employee.is_active.is_(True),
        )
    )
    return count or 0


async def set_approvers(
    session: AsyncSession,
    employee: Employee,
    approver_ids: list[int],
    actor_id: int | None = None,
) -> list[ApproverRead]:
    """Replace the employee's active approver set while preserving historical rows."""
    if not employee.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An inactive employee cannot have leave approvers.",
        )

    ids = list(approver_ids)
    if len(ids) != len(set(ids)):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The approver list contains duplicate ids."
        )
    if len(ids) > MAX_APPROVERS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"At most {MAX_APPROVERS} approvers are allowed.",
        )
    if employee.id in ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An employee cannot be their own approver.",
        )

    if ids:
        approvers = (
            await session.scalars(select(Employee).where(Employee.id.in_(ids)))
        ).all()
        found = {approver.id for approver in approvers}
        missing = [approver_id for approver_id in ids if approver_id not in found]
        if missing:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Approver(s) {missing} do not exist.",
            )
        inactive = [
            approver.employee_code for approver in approvers if not approver.is_active
        ]
        if inactive:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"These approvers are inactive: {', '.join(inactive)}.",
            )

        require_approver_role(
            approvers, await approver_role_holders(session, ids)
        )

    existing = (
        await session.scalars(
            select(EmployeeApprover).where(
                EmployeeApprover.employee_id == employee.id
            )
        )
    ).all()
    by_approver = {row.approver_id: row for row in existing}
    wanted = set(ids)

    removed = {row.approver_id for row in existing if row.is_active} - wanted
    if removed:
        blocked = await session.scalar(
            select(func.count())
            .select_from(LeaveRequestApproval)
            .join(
                LeaveRequest,
                LeaveRequest.id == LeaveRequestApproval.leave_request_id,
            )
            .where(
                LeaveRequest.employee_id == employee.id,
                LeaveRequestApproval.approver_id.in_(removed),
                LeaveRequestApproval.status == ApprovalStatus.PENDING,
                LeaveRequest.status == RequestStatus.PENDING,
            )
        )
        if blocked:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot remove an approver who still has {blocked} pending "
                "request(s) to decide. Ask the employee to cancel the pending "
                "request, or wait for the decision. An administrator can also cancel the "
                "pending request.",
            )

    before_ids = sorted(row.approver_id for row in existing if row.is_active)

    for approver_id, row in by_approver.items():
        row.is_active = approver_id in wanted
    for approver_id in wanted - set(by_approver):
        session.add(
            EmployeeApprover(
                employee_id=employee.id, approver_id=approver_id, is_active=True
            )
        )

    if before_ids != sorted(wanted):
        await record(
            session, actor_id, "employee_approver", employee.id, "APPROVERS_SET",
            old={"approver_ids": before_ids}, new={"approver_ids": sorted(wanted)},
        )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another admin changed these approvers at the same time. "
            "Please reload and try again.",
        ) from None

    return await approver_reads(session, employee.id)


async def ensure_supervisor_is_approver(
    session: AsyncSession, employee: Employee
) -> None:
    return

