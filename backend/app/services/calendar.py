"""Calendar lookup and chargeable-day preview helpers."""

import datetime

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar import CalendarPreview, PreviewDay
from app.models.employee import Employee
from app.models.holiday import Holiday, HolidayType
from app.models.weekend_setting import WeekendSetting
from app.services.day_calc import DayType, calculate_chargeable_days

GLOBAL_WEEKEND_MISSING = (
    "Global weekend is not configured. Ask an admin to set it on the "
    "Calendar settings page."
)


async def weekend_days_for(session: AsyncSession, employee_id: int) -> set[int]:
    override = await session.scalar(
        select(WeekendSetting).where(WeekendSetting.employee_id == employee_id)
    )
    if override is not None:
        return set(override.days_of_week)

    global_setting = await session.scalar(
        select(WeekendSetting).where(WeekendSetting.employee_id.is_(None))
    )
    if global_setting is None:
        raise HTTPException(status.HTTP_409_CONFLICT, GLOBAL_WEEKEND_MISSING)
    return set(global_setting.days_of_week)


async def holidays_in_range(
    session: AsyncSession,
    employee: Employee,
    start_date: datetime.date,
    end_date: datetime.date,
) -> list[Holiday]:
    """Return holidays overlapping the date range for the employee's scope."""
    statement = (
        select(Holiday)
        .where(Holiday.date >= start_date, Holiday.date <= end_date)
        .where(
            or_(
                Holiday.division_id.is_(None),
                Holiday.division_id == employee.division_id,
            ),
            or_(
                Holiday.department_id.is_(None),
                Holiday.department_id == employee.department_id,
            ),
        )
        .order_by(Holiday.date)
    )
    return list((await session.scalars(statement)).all())


async def build_preview(
    session: AsyncSession,
    employee: Employee,
    start_date: datetime.date,
    end_date: datetime.date,
    day_type: DayType,
) -> CalendarPreview:
    weekend = await weekend_days_for(session, employee.id)
    holidays = await holidays_in_range(session, employee, start_date, end_date)

    subtracted: set[datetime.date] = set()
    optional_titles: dict[datetime.date, list[str]] = {}
    for holiday in holidays:
        holiday_type = HolidayType(holiday.type)
        if holiday_type is HolidayType.OPTIONAL:
            optional_titles.setdefault(holiday.date, []).append(holiday.title)
        else:
            subtracted.add(holiday.date)

    result = calculate_chargeable_days(
        start_date, end_date, day_type, weekend, subtracted
    )

    return CalendarPreview(
        start_date=start_date,
        end_date=end_date,
        day_type=day_type,
        employee_id=employee.id,
        weekend_days=sorted(weekend),
        chargeable_days=result.chargeable_days,
        days=[
            PreviewDay(
                date=day.date,
                kind=day.kind,
                optional_holidays=optional_titles.get(day.date, []),
            )
            for day in result.days
        ],
    )
