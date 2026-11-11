from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.models.employee_approver import (
    ApproverRead,
    ApproversUpdate,
    EmployeeApprover,
    EmployeeApproversRead,
)
from app.services.approvers import approver_reads, set_approvers

router = APIRouter(tags=["approvers"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]


@router.put(
    "/employees/{employee_id}/approvers",
    response_model=list[ApproverRead],
    dependencies=ADMIN_ONLY,
)
async def put_employee_approvers(
    employee_id: int,
    payload: ApproversUpdate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> list[ApproverRead]:
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Employee {employee_id} not found."
        )
    return await set_approvers(
        session, employee, payload.approver_ids, actor_id=actor.id
    )


@router.get(
    "/approver-assignments",
    response_model=list[EmployeeApproversRead],
    dependencies=ADMIN_ONLY,
)
async def list_approver_assignments(
    division_id: int | None = None,
    department_id: int | None = None,
    only_missing: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[EmployeeApproversRead]:
    statement = (
        select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.id)
    )
    if division_id is not None:
        statement = statement.where(Employee.division_id == division_id)
    if department_id is not None:
        statement = statement.where(Employee.department_id == department_id)
    employees = (await session.scalars(statement)).all()
    if not employees:
        return []

    rows = (
        await session.scalars(
            select(EmployeeApprover)
            .where(
                EmployeeApprover.employee_id.in_(
                    [employee.id for employee in employees]
                ),
                EmployeeApprover.is_active.is_(True),
            )
            .order_by(EmployeeApprover.approver_id)
        )
    ).all()

    by_employee: dict[int, list[int]] = {employee.id: [] for employee in employees}
    for row in rows:
        by_employee[row.employee_id].append(row.approver_id)

    if only_missing:
        employees = [
            employee for employee in employees if not by_employee[employee.id]
        ]
        if not employees:
            return []

    approver_ids = {
        approver_id
        for employee in employees
        for approver_id in by_employee[employee.id]
    }
    people = {}
    if approver_ids:
        people = {
            person.id: person
            for person in (
                await session.scalars(
                    select(Employee).where(Employee.id.in_(approver_ids))
                )
            ).all()
        }

    return [
        EmployeeApproversRead(
            employee_id=employee.id,
            employee_code=employee.employee_code,
            employee_name=employee.full_name,
            division_id=employee.division_id,
            department_id=employee.department_id,
            supervisor_id=employee.supervisor_id,
            approvers=[
                ApproverRead(
                    id=approver_id,
                    employee_code=people[approver_id].employee_code,
                    full_name=people[approver_id].full_name,
                    is_supervisor=(approver_id == employee.supervisor_id),
                )
                for approver_id in by_employee[employee.id]
                if approver_id in people
            ],
        )
        for employee in employees
    ]


@router.get("/approvers/me", response_model=list[ApproverRead])
async def my_approvers(
    current: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ApproverRead]:
    return await approver_reads(session, current.id)
