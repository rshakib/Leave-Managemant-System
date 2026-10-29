from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.models.employee import Role
from app.db.session import get_session
from app.models.division import (
    Division,
    DivisionCreate,
    DivisionRead,
    DivisionUpdate,
)
from app.models.employee import Employee, Role
from app.services.audit import record, snapshot

router = APIRouter(prefix="/divisions", tags=["divisions"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]


@router.post(
    "",
    response_model=DivisionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN_ONLY,
)
async def create_division(
    payload: DivisionCreate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> DivisionRead:
    existing = await session.scalar(
        select(Division).where(Division.name == payload.name)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A division named '{payload.name}' already exists.",
        )

    division = Division(name=payload.name, is_active=payload.is_active)
    session.add(division)
    await session.flush()
    await record(
        session, actor.id, "division", division.id, "CREATE",
        new=snapshot(division, ("name", "is_active")),
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A division named '{payload.name}' already exists.",
        ) from None
    await session.refresh(division)
    return DivisionRead.model_validate(division)


@router.get("", response_model=list[DivisionRead], dependencies=LOGGED_IN)
async def list_divisions(
    session: AsyncSession = Depends(get_session),
) -> list[DivisionRead]:
    result = await session.scalars(select(Division).order_by(Division.id))
    return [DivisionRead.model_validate(d) for d in result.all()]


@router.get("/{division_id}", response_model=DivisionRead, dependencies=LOGGED_IN)
async def get_division(
    division_id: int,
    session: AsyncSession = Depends(get_session),
) -> DivisionRead:
    division = await session.get(Division, division_id)
    if division is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Division not found."
        )
    return DivisionRead.model_validate(division)


@router.patch("/{division_id}", response_model=DivisionRead, dependencies=ADMIN_ONLY)
async def update_division(
    division_id: int,
    payload: DivisionUpdate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> DivisionRead:
    division = await session.get(Division, division_id)
    if division is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Division not found."
        )

    before = snapshot(division, ("name", "is_active"))

    if payload.is_active is False and division.is_active:
        active_employees = await session.scalar(
            select(func.count())
            .select_from(Employee)
            .where(Employee.division_id == division_id, Employee.is_active.is_(True))
        )
        if active_employees:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot deactivate division {division_id}: it still has "
                    f"{active_employees} active employee(s)."
                ),
            )

    if payload.name is not None and payload.name != division.name:
        clash = await session.scalar(
            select(Division).where(
                Division.name == payload.name, Division.id != division_id
            )
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A division named '{payload.name}' already exists.",
            )
        division.name = payload.name

    if payload.is_active is not None:
        division.is_active = payload.is_active

    after = snapshot(division, ("name", "is_active"))
    if before != after:
        action = "UPDATE"
        if before["is_active"] and not after["is_active"]:
            action = "DEACTIVATE"
        elif not before["is_active"] and after["is_active"]:
            action = "ACTIVATE"
        await record(session, actor.id, "division", division.id, action,
                     old=before, new=after)

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A division with that name already exists.",
        ) from None
    await session.refresh(division)
    return DivisionRead.model_validate(division)


@router.delete(
    "/{division_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN_ONLY,
)
async def delete_division(
    division_id: int,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
):
    """Hard-delete an EMPTY division. Anything still pointing at it answers 409."""
    from sqlalchemy import func, select

    from app.models.department import Department
    from app.models.division import Division
    from app.models.employee import Employee
    from app.models.holiday import Holiday
    from app.services.audit import record

    division = await session.get(Division, division_id)
    if division is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Division not found.")

    async def count(model, column):
        return await session.scalar(
            select(func.count()).select_from(model).where(column == division_id)
        )

    blockers = {
        "department(s)": await count(Department, Department.division_id),
        "employee(s)": await count(Employee, Employee.division_id),
        "holiday(ies)": await count(Holiday, Holiday.division_id),
    }
    used = {label: n for label, n in blockers.items() if n}
    if used:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This division is still in use: "
            + ", ".join(f"{n} {label}" for label, n in used.items())
            + ". Deactivate it instead of deleting.",
        )

    await record(
        session,
        actor.id,
        "division",
        division_id,
        "DELETE",
        old={"name": division.name, "is_active": division.is_active},
    )
    await session.delete(division)
    await session.commit()
    return None
