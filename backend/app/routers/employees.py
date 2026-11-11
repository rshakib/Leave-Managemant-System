from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, load_roles, require_roles
from app.core.security import hash_password
from app.db.session import get_session
from app.models.department import Department
from app.models.division import Division
from app.models.employee import (
    Employee,
    EmployeeCreate,
    EmployeeRead,
    EmployeeRole,
    EmployeeUpdate,
    Role,
    employee_to_read,
    unique_roles,
    with_employee_role,
)
from app.services.approvals import pending_approval_count, pending_request_count
from app.services.audit import record, snapshot
from app.services.auth_service import revoke_all
from app.services.password_rules import requires_password_change
from app.services.security_rules import check_password_policy
from app.services.approvers import active_approver_count_for_others

router = APIRouter(prefix="/employees", tags=["employees"])

EMPLOYEE_FIELDS = (
    "employee_code",
    "full_name",
    "email",
    "phone",
    "designation",
    "division_id",
    "department_id",
    "supervisor_id",
    "joining_date",
    "is_active",
)

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]


async def _get_employee_or_404(session: AsyncSession, employee_id: int) -> Employee:
    employee = await session.get(Employee, employee_id)
    if employee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Employee not found."
        )
    return employee


async def _validate_placement(
    session: AsyncSession, division_id: int, department_id: int
) -> None:
    division = await session.get(Division, division_id)
    if division is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Division {division_id} does not exist.",
        )
    if not division.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Division {division_id} is inactive.",
        )

    department = await session.get(Department, department_id)
    if department is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Department {department_id} does not exist.",
        )
    if not department.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Department {department_id} is inactive.",
        )
    if department.division_id != division_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Department {department_id} belongs to division "
                f"{department.division_id}, not division {division_id}."
            ),
        )


async def _creates_cycle(
    session: AsyncSession, employee_id: int, supervisor_id: int
) -> bool:
    seen: set[int] = set()
    current: int | None = supervisor_id
    while current is not None:
        if current == employee_id or current in seen:
            return True
        seen.add(current)
        current = await session.scalar(
            select(Employee.supervisor_id).where(Employee.id == current)
        )
    return False


async def _validate_supervisor(
    session: AsyncSession, employee_id: int | None, supervisor_id: int | None
) -> None:
    if supervisor_id is None:
        return
    if employee_id is not None and supervisor_id == employee_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An employee cannot be their own supervisor.",
        )

    supervisor = await session.get(Employee, supervisor_id)
    if supervisor is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Supervisor {supervisor_id} does not exist.",
        )
    if not supervisor.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Supervisor {supervisor_id} is not active.",
        )

    if employee_id is not None and await _creates_cycle(
        session, employee_id, supervisor_id
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot assign {supervisor.full_name} as supervisor: that creates a circular reporting chain (they already report to this employee).",
        )


async def _active_reports(session: AsyncSession, employee_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(Employee)
        .where(Employee.supervisor_id == employee_id, Employee.is_active.is_(True))
    )
    return count or 0


@router.post(
    "",
    response_model=EmployeeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN_ONLY,
)
async def create_employee(
    payload: EmployeeCreate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> EmployeeRead:
    await _validate_placement(session, payload.division_id, payload.department_id)
    await _validate_supervisor(session, None, payload.supervisor_id)

    if await session.scalar(
        select(Employee).where(Employee.employee_code == payload.employee_code)
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Employee code '{payload.employee_code}' already exists.",
        )
    if await session.scalar(select(Employee).where(Employee.email == payload.email)):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An employee with email '{payload.email}' already exists.",
        )

    problems = check_password_policy(payload.password, payload.email)
    if problems:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problems)

    roles = with_employee_role(payload.roles)
    employee = Employee(
        **payload.model_dump(exclude={"roles", "password"}),
        password_hash=hash_password(payload.password),
    )
    session.add(employee)
    try:
        await session.flush()
        for role in roles:
            session.add(EmployeeRole(employee_id=employee.id, role=role))
        await record(
            session, actor.id, "employee", employee.id, "CREATE",
            new={**snapshot(employee, EMPLOYEE_FIELDS),
                 "roles": sorted(role.value for role in roles)},
        )
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Employee code or email already exists.",
        ) from None
    await session.refresh(employee)
    return employee_to_read(employee, roles)


@router.get("", response_model=list[EmployeeRead], dependencies=ADMIN_ONLY)
async def list_employees(
    division_id: int | None = None,
    department_id: int | None = None,
    is_active: bool | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[EmployeeRead]:
    statement = select(Employee).order_by(Employee.id)
    if division_id is not None:
        statement = statement.where(Employee.division_id == division_id)
    if department_id is not None:
        statement = statement.where(Employee.department_id == department_id)
    if is_active is not None:
        statement = statement.where(Employee.is_active == is_active)

    employees = (await session.scalars(statement)).all()
    role_map: dict[int, list[Role]] = {employee.id: [] for employee in employees}
    if employees:
        rows = await session.scalars(
            select(EmployeeRole).where(
                EmployeeRole.employee_id.in_(list(role_map.keys()))
            )
        )
        for row in rows.all():
            role_map[row.employee_id].append(row.role)

    return [
        employee_to_read(employee, role_map[employee.id]) for employee in employees
    ]


@router.get("/{employee_id}", response_model=EmployeeRead, dependencies=ADMIN_ONLY)
async def get_employee(
    employee_id: int,
    session: AsyncSession = Depends(get_session),
) -> EmployeeRead:
    employee = await _get_employee_or_404(session, employee_id)
    return employee_to_read(employee, await load_roles(session, employee_id))


@router.patch("/{employee_id}", response_model=EmployeeRead, dependencies=ADMIN_ONLY)
async def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> EmployeeRead:
    employee = await _get_employee_or_404(session, employee_id)
    data = payload.model_dump(exclude_unset=True)
    before = snapshot(employee, EMPLOYEE_FIELDS)
    old_roles = sorted(role.value for role in await load_roles(session, employee_id))

    supervisor_changed = (
        "supervisor_id" in data and data["supervisor_id"] != employee.supervisor_id
    )

    new_division_id = data.get("division_id", employee.division_id)
    new_department_id = data.get("department_id", employee.department_id)
    if "division_id" in data or "department_id" in data:
        await _validate_placement(session, new_division_id, new_department_id)

    if "supervisor_id" in data:
        await _validate_supervisor(session, employee_id, data["supervisor_id"])

    if "employee_code" in data and data["employee_code"] != employee.employee_code:
        clash = await session.scalar(
            select(Employee).where(
                Employee.employee_code == data["employee_code"],
                Employee.id != employee_id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Employee code '{data['employee_code']}' already exists.",
            )

    if "email" in data and data["email"] != employee.email:
        clash = await session.scalar(
            select(Employee).where(
                Employee.email == data["email"], Employee.id != employee_id
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An employee with email '{data['email']}' already exists.",
            )

    if data.get("is_active") is False and employee.is_active:
        reports = await _active_reports(session, employee_id)
        if reports:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot deactivate: this employee supervises {reports} active "
                    "employee(s). Reassign the supervisor first (DECISIONS D-40)."
                ),
            )

        approving_for = await active_approver_count_for_others(session, employee_id)
        if approving_for:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot deactivate: this employee is an active approver for "
                    f"{approving_for} active employee(s). Reassign those approvers "
                    "first (DECISIONS D-81)."
                ),
            )

        pending_requests = await pending_request_count(session, employee_id)
        pending_decisions = await pending_approval_count(session, employee_id)
        if pending_requests or pending_decisions:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot deactivate: this employee has {pending_requests} "
                    f"pending leave request(s) and {pending_decisions} pending "
                    "approval(s) to decide. Resolve them first — an administrator can cancel "
                    "a pending request (DECISIONS D-94)."
                ),
            )

    if "roles" in data:
        new_roles = set(with_employee_role(payload.roles or []))
        if Role.APPROVER not in new_roles:
            approving_for = await active_approver_count_for_others(
                session, employee_id
            )
            if approving_for:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Cannot remove the APPROVER role: this employee is still an "
                        f"active approver for {approving_for} active employee(s). "
                        "Reassign those approvers first (DECISIONS D-82)."
                    ),
                )

            pending_decisions = await pending_approval_count(session, employee_id)
            if pending_decisions:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Cannot remove the APPROVER role: this employee still has "
                        f"{pending_decisions} pending approval(s) to decide "
                        "(DECISIONS D-95)."
                    ),
                )

    new_password = data.pop("password", None)

    for field, value in data.items():
        if field != "roles":
            setattr(employee, field, value)

    if new_password is not None:
        problems = check_password_policy(new_password, employee.email)
        if problems:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, problems)
        employee.password_hash = hash_password(new_password)
        employee.must_change_password = requires_password_change(
            actor_id=actor.id,
            target_id=employee_id,
            password_set=True,
            explicit=payload.must_change_password,
        )
        await revoke_all(session, employee_id)

    if "roles" in data:
        await session.execute(
            delete(EmployeeRole).where(EmployeeRole.employee_id == employee_id)
        )
        for role in with_employee_role(payload.roles or []):
            session.add(EmployeeRole(employee_id=employee_id, role=role))

    after = snapshot(employee, EMPLOYEE_FIELDS)
    changes = {
        key: value for key, value in after.items() if before.get(key) != value
    }
    if changes:
        action = "UPDATE"
        if before["is_active"] and not after["is_active"]:
            action = "DEACTIVATE"
        elif not before["is_active"] and after["is_active"]:
            action = "ACTIVATE"
        await record(
            session, actor.id, "employee", employee_id, action,
            old={key: before[key] for key in changes}, new=changes,
        )
    if "roles" in data:
        new_roles = sorted(role.value for role in with_employee_role(payload.roles or []))
        if new_roles != old_roles:
            await record(
                session, actor.id, "employee", employee_id, "ROLES_CHANGED",
                old={"roles": old_roles}, new={"roles": new_roles},
            )
    if data.get("is_active") is False and not employee.is_active:
        await revoke_all(session, employee_id)

    if new_password is not None:
        await record(
            session, actor.id, "employee", employee_id, "PASSWORD_RESET",
            reason="password reset by an administrator",
        )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Employee code or email already exists.",
        ) from None
    await session.refresh(employee)
    return employee_to_read(employee, await load_roles(session, employee_id))
