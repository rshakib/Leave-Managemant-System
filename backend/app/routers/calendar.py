import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, load_roles
from app.db.session import get_session
from app.models.calendar import CalendarPreview
from app.models.employee import Employee, Role
from app.services.calendar import build_preview
from app.services.day_calc import DayCalcError, DayType

router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/preview", response_model=CalendarPreview)
async def preview_calendar(
    start_date: datetime.date,
    end_date: datetime.date,
    day_type: DayType = DayType.FULL_DAY,
    employee_id: int | None = None,
    current: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> CalendarPreview:
    """Chargeable days plus the per-day breakdown for a date range.

    `employee_id` defaults to the signed-in user. Only an ADMIN may look at
    somebody else's calendar.
    """
    if employee_id is not None and employee_id != current.id:
        if Role.ADMIN not in await load_roles(session, current.id):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only preview your own calendar.",
            )
        employee = await session.get(Employee, employee_id)
        if employee is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Employee {employee_id} not found."
            )
    else:
        employee = current

    try:
        return await build_preview(
            session, employee, start_date, end_date, day_type
        )
    except DayCalcError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
