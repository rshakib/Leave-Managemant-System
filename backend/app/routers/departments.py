from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.department import (
    Department,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
)
from app.models.division import Division
from app.models.employee import Employee, Role
from app.services.audit import record, snapshot

router = APIRouter(prefix="/departments", tags=["departments"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]


@router.post(
    "",
    response_model=DepartmentRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN_ONLY,
)
async def create_department(
    payload: DepartmentCreate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> DepartmentRead:
    division = await session.get(Division, payload.division_id)
    if division is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Division {payload.division_id} not found.",
        )
    if not division.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create a department under an inactive division.",
        )

    clash = await session.scalar(
        select(Department).where(
            Department.division_id == payload.division_id,
            Department.name == payload.name,
        )
    )
    if clash is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Department '{payload.name}' already exists in this division.",
        )

    department = Department(
        division_id=payload.division_id,
        name=payload.name,
        is_active=payload.is_active,
    )
    session.add(department)
    await session.flush()
    await record(
        session, actor.id, "department", department.id, "CREATE",
        new=snapshot(department, ("division_id", "name", "is_active")),
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Department '{payload.name}' already exists in this division.",
        ) from None
    await session.refresh(department)
    return DepartmentRead.model_validate(department)


@router.get("", response_model=list[DepartmentRead], dependencies=LOGGED_IN)
async def list_departments(
    division_id: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[DepartmentRead]:
    statement = select(Department).order_by(Department.id)
    if division_id is not None:
        statement = statement.where(Department.division_id == division_id)
    result = await session.scalars(statement)
    return [DepartmentRead.model_validate(d) for d in result.all()]


@router.get("/{department_id}", response_model=DepartmentRead, dependencies=LOGGED_IN)
async def get_department(
    department_id: int,
    session: AsyncSession = Depends(get_session),
) -> DepartmentRead:
    department = await session.get(Department, department_id)
    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Department not found."
        )
    return DepartmentRead.model_validate(department)


@router.patch(
    "/{department_id}", response_model=DepartmentRead, dependencies=ADMIN_ONLY
)
async def update_department(
    department_id: int,
    payload: DepartmentUpdate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> DepartmentRead:
    department = await session.get(Department, department_id)
    if department is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Department not found."
        )

    before = snapshot(department, ("name", "is_active"))

    if payload.is_active is False and department.is_active:
        active_employees = await session.scalar(
            select(func.count())
            .select_from(Employee)
            .where(
                Employee.department_id == department_id,
                Employee.is_active.is_(True),
            )
        )
        if active_employees:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot deactivate department {department_id}: it still has "
                    f"{active_employees} active employee(s)."
                ),
            )

    if payload.name is not None and payload.name != department.name:
        clash = await session.scalar(
            select(Department).where(
                Department.division_id == department.division_id,
                Department.name == payload.name,
                Department.id != department_id,
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Department '{payload.name}' already exists in this division.",
            )
        department.name = payload.name

    if payload.is_active is not None:
        department.is_active = payload.is_active

    after = snapshot(department, ("name", "is_active"))
    if before != after:
        action = "UPDATE"
        if before["is_active"] and not after["is_active"]:
            action = "DEACTIVATE"
        elif not before["is_active"] and after["is_active"]:
            action = "ACTIVATE"
        await record(session, actor.id, "department", department.id, action,
                     old=before, new=after)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Department name must be unique within its division.",
        ) from None
    await session.refresh(department)
    return DepartmentRead.model_validate(department)


@router.delete(
    "/{department_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN_ONLY,
)
async def delete_department(
    department_id: int,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
):
    """Hard-delete an EMPTY department. Anything still pointing at it answers 409."""
    from sqlalchemy import func, select

    from app.models.department import Department
    from app.models.employee import Employee
    from app.models.holiday import Holiday
    from app.services.audit import record

    department = await session.get(Department, department_id)
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found.")

    async def count(model, column):
        return await session.scalar(
            select(func.count()).select_from(model).where(column == department_id)
        )

    blockers = {
        "employee(s)": await count(Employee, Employee.department_id),
        "holiday(ies)": await count(Holiday, Holiday.department_id),
    }
    used = {label: n for label, n in blockers.items() if n}
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This department is still in use: "
            + ", ".join(f"{n} {label}" for label, n in used.items())
            + ". Deactivate it instead of deleting.",
        )

    await record(
        session,
        actor.id,
        "department",
        department_id,
        "DELETE",
        old={"name": department.name, "is_active": department.is_active},
    )
    await session.delete(department)
    await session.commit()
    return None
