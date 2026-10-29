import datetime
from decimal import Decimal

from sqlmodel import Field, SQLModel

from app.services.day_calc import DayKind, DayType


class PreviewDay(SQLModel):
    """One day of a calendar preview."""

    date: datetime.date
    kind: DayKind
    # Titles of OPTIONAL holidays on this date: shown, but not subtracted.
    optional_holidays: list[str] = Field(default_factory=list)


class CalendarPreview(SQLModel):
    start_date: datetime.date
    end_date: datetime.date
    day_type: DayType
    employee_id: int
    weekend_days: list[int]
    chargeable_days: Decimal
    days: list[PreviewDay]
