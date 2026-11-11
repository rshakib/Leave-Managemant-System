import csv
import datetime
import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.department import Department
from app.models.division import Division
from app.models.employee import Employee, Role
from app.services.audit import record, snapshot
from app.models.holiday import (
    Holiday,
    HolidayCreate,
    HolidayImportResult,
    HolidayRead,
    HolidayType,
    HolidayUpdate,
)
from app.models.leave_year import LeaveYear

router = APIRouter(prefix="/holidays", tags=["holidays"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]
LOGGED_IN = [Depends(get_current_user)]

MAX_IMPORT_BYTES = 1_000_000
MAX_IMPORT_ROWS = 1000


async def _leave_year_or_404(session: AsyncSession, leave_year_id: int) -> LeaveYear:
    year = await session.get(LeaveYear, leave_year_id)
    if year is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Leave year {leave_year_id} not found."
        )
    return year


def _check_inside_year(year: LeaveYear, dates: list[datetime.date]) -> None:
    outside = [value for value in dates if value < year.start_date or value > year.end_date]
    if outside:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{outside[0]} is outside leave year '{year.name}' "
            f"({year.start_date}..{year.end_date}).",
        )


async def _resolve_scope(
    session: AsyncSession,
    division_id: int | None,
    department_id: int | None,
) -> tuple[int | None, int | None]:
    if department_id is not None:
        department = await session.get(Department, department_id)
        if department is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Department {department_id} not found."
            )
        if division_id is not None and division_id != department.division_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Department {department_id} belongs to division "
                f"{department.division_id}, not division {division_id}.",
            )
        return department.division_id, department.id

    if division_id is not None:
        division = await session.get(Division, division_id)
        if division is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Division {division_id} not found."
            )
        return division.id, None

    return None, None


async def _duplicate_for(
    session: AsyncSession,
    dates: list[datetime.date],
    division_id: int | None,
    department_id: int | None,
) -> Holiday | None:
    rows = (
        await session.scalars(select(Holiday).where(Holiday.date.in_(dates)))
    ).all()
    for row in rows:
        if row.division_id == division_id and row.department_id == department_id:
            return row
    return None


@router.post(
    "",
    response_model=list[HolidayRead],
    status_code=status.HTTP_201_CREATED,
    dependencies=ADMIN_ONLY,
)
async def create_holidays(
    payload: HolidayCreate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> list[HolidayRead]:
    year = await _leave_year_or_404(session, payload.leave_year_id)
    dates = payload.dates
    _check_inside_year(year, dates)

    division_id, department_id = await _resolve_scope(
        session, payload.division_id, payload.department_id
    )

    clash = await _duplicate_for(session, dates, division_id, department_id)
    if clash is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A holiday already exists on {clash.date} for the same scope "
            f"('{clash.title}').",
        )

    created = [
        Holiday(
            leave_year_id=year.id,
            date=holiday_date,
            title=payload.title,
            type=payload.type,
            division_id=division_id,
            department_id=department_id,
        )
        for holiday_date in dates
    ]
    session.add_all(created)
    await session.flush()
    await record(
        session, actor.id, "holiday", created[0].id, "CREATE",
        new={
            "dates": [row.date for row in created],
            "title": payload.title,
            "type": payload.type,
            "division_id": division_id,
            "department_id": department_id,
        },
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "One of those dates already has a holiday for the same scope.",
        ) from None

    for row in created:
        await session.refresh(row)
    return [HolidayRead.model_validate(row) for row in created]


@router.get("", response_model=list[HolidayRead], dependencies=LOGGED_IN)
async def list_holidays(
    leave_year_id: int | None = None,
    division_id: int | None = None,
    department_id: int | None = None,
    type: HolidayType | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[HolidayRead]:
    statement = select(Holiday).order_by(Holiday.date)
    if leave_year_id is not None:
        statement = statement.where(Holiday.leave_year_id == leave_year_id)
    if division_id is not None:
        statement = statement.where(Holiday.division_id == division_id)
    if department_id is not None:
        statement = statement.where(Holiday.department_id == department_id)
    if type is not None:
        statement = statement.where(Holiday.type == type)
    rows = (await session.scalars(statement)).all()
    return [HolidayRead.model_validate(row) for row in rows]


@router.patch("/{holiday_id}", response_model=HolidayRead, dependencies=ADMIN_ONLY)
async def update_holiday(
    holiday_id: int,
    payload: HolidayUpdate,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> HolidayRead:
    holiday = await session.get(Holiday, holiday_id)
    if holiday is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found.")

    before = snapshot(holiday, ("leave_year_id", "date", "title", "type", "division_id", "department_id"))
    data = payload.model_dump(exclude_unset=True)

    if "date" in data:
        year = await _leave_year_or_404(session, holiday.leave_year_id)
        _check_inside_year(year, [data["date"]])

    if "division_id" in data or "department_id" in data:
        division_id, department_id = await _resolve_scope(
            session, data.get("division_id"), data.get("department_id")
        )
        data["division_id"] = division_id
        data["department_id"] = department_id

    for field, value in data.items():
        setattr(holiday, field, value)

    after = snapshot(holiday, ("leave_year_id", "date", "title", "type", "division_id", "department_id"))
    changes = {key: value for key, value in after.items() if before.get(key) != value}
    if changes:
        await record(
            session, actor.id, "holiday", holiday_id, "UPDATE",
            old={key: before[key] for key in changes}, new=changes,
        )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Another holiday already exists on that date for the same scope.",
        ) from None
    await session.refresh(holiday)
    return HolidayRead.model_validate(holiday)


@router.delete(
    "/{holiday_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=ADMIN_ONLY,
)
async def delete_holiday(
    holiday_id: int,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> None:
    holiday = await session.get(Holiday, holiday_id)
    if holiday is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday not found.")
    await record(
        session, actor.id, "holiday", holiday_id, "DELETE",
        old=snapshot(holiday, ("leave_year_id", "date", "title", "type", "division_id", "department_id")),
    )
    await session.delete(holiday)
    await session.commit()


@router.post("/import", response_model=HolidayImportResult, dependencies=ADMIN_ONLY)
async def import_holidays(
    leave_year_id: int = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> HolidayImportResult:
    year = await _leave_year_or_404(session, leave_year_id)

    raw = await file.read()
    if len(raw) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The CSV file is larger than 1 MB."
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "The CSV file must be UTF-8 encoded."
        ) from None

    rows = list(csv.DictReader(io.StringIO(text)))
    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"The CSV file has more than {MAX_IMPORT_ROWS} rows.",
        )

    divisions = {
        division.name.lower(): division
        for division in (await session.scalars(select(Division))).all()
    }
    departments = {
        (department.division_id, department.name.lower()): department
        for department in (await session.scalars(select(Department))).all()
    }

    errors: list[dict[str, object]] = []
    prepared: list[dict[str, object]] = []
    seen: set[tuple[datetime.date, int | None, int | None]] = set()

    for index, row in enumerate(rows, start=2):
        raw_date = (row.get("date") or "").strip()
        try:
            holiday_date = datetime.date.fromisoformat(raw_date)
        except ValueError:
            errors.append(
                {"row": index, "message": f"'{raw_date}' is not YYYY-MM-DD."}
            )
            continue

        if holiday_date < year.start_date or holiday_date > year.end_date:
            errors.append(
                {
                    "row": index,
                    "message": f"{holiday_date} is outside leave year '{year.name}'.",
                }
            )
            continue

        title = (row.get("title") or "").strip()
        if not title:
            errors.append({"row": index, "message": "title is required."})
            continue

        raw_type = (row.get("type") or HolidayType.PUBLIC.value).strip().upper()
        try:
            holiday_type = HolidayType(raw_type)
        except ValueError:
            errors.append(
                {
                    "row": index,
                    "message": f"'{raw_type}' is not PUBLIC, COMPANY or OPTIONAL.",
                }
            )
            continue

        division_name = (row.get("division") or "").strip()
        department_name = (row.get("department") or "").strip()

        division = None
        if division_name:
            division = divisions.get(division_name.lower())
            if division is None:
                errors.append(
                    {"row": index, "message": f"unknown division '{division_name}'."}
                )
                continue

        department = None
        if department_name:
            if division is None:
                errors.append(
                    {
                        "row": index,
                        "message": "a department needs a division in the same row.",
                    }
                )
                continue
            department = departments.get((division.id, department_name.lower()))
            if department is None:
                errors.append(
                    {
                        "row": index,
                        "message": f"unknown department '{department_name}' in that division.",
                    }
                )
                continue

        if department is not None:
            scope = (department.division_id, department.id)
        elif division is not None:
            scope = (division.id, None)
        else:
            scope = (None, None)

        key = (holiday_date, scope[0], scope[1])
        if key in seen:
            errors.append(
                {
                    "row": index,
                    "message": f"{holiday_date} is listed twice for the same scope.",
                }
            )
            continue
        seen.add(key)
        prepared.append(
            {
                "date": holiday_date,
                "title": title,
                "type": holiday_type,
                "division_id": scope[0],
                "department_id": scope[1],
            }
        )

    if errors:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={
                "message": f"{len(errors)} row(s) could not be imported; nothing was saved.",
                "errors": errors,
            },
        )

    if prepared:
        dates = [item["date"] for item in prepared]
        existing = (
            await session.scalars(select(Holiday).where(Holiday.date.in_(dates)))
        ).all()
        existing_keys = {
            (row.date, row.division_id, row.department_id) for row in existing
        }
        clash = next(
            (
                item
                for item in prepared
                if (item["date"], item["division_id"], item["department_id"])
                in existing_keys
            ),
            None,
        )
        if clash is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A holiday already exists on {clash['date']} for the same scope. "
                "Nothing was imported.",
            )

        rows = [Holiday(leave_year_id=year.id, **item) for item in prepared]
        session.add_all(rows)
        await session.flush()
        await record(
            session, actor.id, "holiday", None, "IMPORT",
            new={
                "leave_year_id": year.id,
                "created": len(rows),
                "holiday_ids": [row.id for row in rows],
                "dates": [row.date for row in rows][:50],
                "dates_truncated": len(rows) > 50,
                "source": "CSV import",
            },
        )
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A holiday already exists for one of those dates. Nothing was imported.",
            ) from None

    return HolidayImportResult(created=len(prepared))
