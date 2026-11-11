from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.services.audit import record, snapshot
from app.models.leave_year import (
    LeaveYear,
    LeaveYearCreate,
    LeaveYearRead,
    LeaveYearUpdate,
)

router = APIRouter(prefix="/leave-years", tags=["leave-years"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]


async def _reads(session: AsyncSession, years: list[LeaveYear]) -> list[LeaveYearRead]:
    closer_ids = {year.closed_by_id for year in years if year.closed_by_id}
    names: dict[int, str] = {}
    if closer_ids:
        names = {
            employee.id: employee.full_name
            for employee in (
                await session.scalars(
                    select(Employee).where(Employee.id.in_(closer_ids))
                )
            ).all()
        }
    return [
        LeaveYearRead.model_validate(year).model_copy(
            update={"closed_by_name": names.get(year.closed_by_id)}
        )
        for year in years
    ]


async def _get_or_404(session: AsyncSession, year_id: int) -> LeaveYear:
    year = await session.get(LeaveYear, year_id)
    if year is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave year not found.")
    return year


def _check_order(start_date: date, end_date: date) -> None:
    if end_date < start_date:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"end_date ({end_date}) must not be before start_date ({start_date}).",
        )


async def _ensure_name_free(
    session: AsyncSession, name: str, exclude_id: int | None = None
) -> None:
    statement = select(LeaveYear).where(LeaveYear.name == name)
    if exclude_id is not None:
        statement = statement.where(LeaveYear.id != exclude_id)
    if await session.scalar(statement.limit(1)) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"A leave year named '{name}' already exists."
        )


async def _ensure_no_overlap(
    session: AsyncSession,
    start_date: date,
    end_date: date,
    exclude_id: int | None = None,
) -> None:
    statement = select(LeaveYear).where(
        LeaveYear.start_date <= end_date, LeaveYear.end_date >= start_date
    )
    if exclude_id is not None:
        statement = statement.where(LeaveYear.id != exclude_id)
    clash = await session.scalar(statement.limit(1))
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Date range {start_date}..{end_date} overlaps leave year "
            f"'{clash.name}' ({clash.start_date}..{clash.end_date}).",
        )


@router.post(
    "",
    response_model=LeaveYearRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN_ONLY,
)
async def create_leave_year(
    payload: LeaveYearCreate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> LeaveYearRead:
    _check_order(payload.start_date, payload.end_date)
    await _ensure_name_free(session, payload.name)
    await _ensure_no_overlap(session, payload.start_date, payload.end_date)

    year = LeaveYear(
        name=payload.name,
        start_date=payload.start_date,
        end_date=payload.end_date,
    )
    session.add(year)
    await session.flush()
    await record(
        session, actor.id, "leave_year", year.id, "CREATE",
        new=snapshot(year, ("name", "start_date", "end_date")),
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A leave year with that name already exists.",
        ) from None
    await session.refresh(year)
    return LeaveYearRead.model_validate(year)


@router.get("", response_model=list[LeaveYearRead], dependencies=LOGGED_IN)
async def list_leave_years(
    session: AsyncSession = Depends(get_session),
) -> list[LeaveYearRead]:
    result = await session.scalars(select(LeaveYear).order_by(LeaveYear.start_date))
    return await _reads(session, list(result.all()))


@router.get("/{year_id}", response_model=LeaveYearRead, dependencies=LOGGED_IN)
async def get_leave_year(
    year_id: int,
    session: AsyncSession = Depends(get_session),
) -> LeaveYearRead:
    year = await _get_or_404(session, year_id)
    return (await _reads(session, [year]))[0]


@router.patch("/{year_id}", response_model=LeaveYearRead, dependencies=ADMIN_ONLY)
async def update_leave_year(
    year_id: int,
    payload: LeaveYearUpdate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> LeaveYearRead:
    year = await _get_or_404(session, year_id)
    if year.is_closed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This leave year is closed and cannot be edited.",
        )

    data = payload.model_dump(exclude_unset=True)
    before = snapshot(year, ("name", "start_date", "end_date"))

    new_start = data.get("start_date", year.start_date)
    new_end = data.get("end_date", year.end_date)
    _check_order(new_start, new_end)

    if "name" in data and data["name"] != year.name:
        await _ensure_name_free(session, data["name"], exclude_id=year_id)

    if "start_date" in data or "end_date" in data:
        await _ensure_no_overlap(session, new_start, new_end, exclude_id=year_id)

    for field, value in data.items():
        setattr(year, field, value)

    after = snapshot(year, ("name", "start_date", "end_date"))
    changes = {key: value for key, value in after.items() if before.get(key) != value}
    if changes:
        await record(
            session, actor.id, "leave_year", year_id, "UPDATE",
            old={key: before[key] for key in changes}, new=changes,
        )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A leave year with that name already exists.",
        ) from None
    await session.refresh(year)
    return LeaveYearRead.model_validate(year)


@router.post(
    "/{year_id}/activate",
    response_model=LeaveYearRead,
    dependencies=ADMIN_ONLY,
)
async def activate_leave_year(
    year_id: int,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> LeaveYearRead:
    year = await _get_or_404(session, year_id)
    if year.is_closed:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "A closed leave year cannot be activated."
        )

    await record(
        session, actor.id, "leave_year", year_id, "ACTIVATE",
        reason=f"'{year.name}' became the active leave year",
    )

    try:
        await session.execute(
            update(LeaveYear)
            .where(LeaveYear.is_active.is_(True), LeaveYear.id != year_id)
            .values(is_active=False)
        )
        year.is_active = True
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another leave year is already active. Please try again.",
        ) from None

    await session.refresh(year)
    return LeaveYearRead.model_validate(year)
