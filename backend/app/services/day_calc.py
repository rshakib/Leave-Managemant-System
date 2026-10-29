"""The pure day-calculation engine (FR-CAL-4).

This module has NO database, NO FastAPI and NO clock: it is a plain function in,
a result out. That makes it fast and easy to test, and lets both the calendar
preview and the Phase-10 leave-request validation reuse exactly the same rules.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

# The longest range we accept (a leave year plus a little slack).
MAX_RANGE_DAYS = 366

WEEKEND = "WEEKEND"
HOLIDAY = "HOLIDAY"
WORKING = "WORKING"


class DayCalcError(ValueError):
    """Raised when the requested range or day type cannot be calculated."""


class DayKind(str, Enum):
    """What a single day in the range is."""

    WORKING = "WORKING"
    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"


class DayType(str, Enum):
    FULL_DAY = "FULL_DAY"
    FIRST_HALF = "FIRST_HALF"
    SECOND_HALF = "SECOND_HALF"


@dataclass(frozen=True)
class DayResult:
    """One day of the range, with the reason it was (or was not) chargeable."""

    date: date
    kind: DayKind


@dataclass(frozen=True)
class DayCalcResult:
    chargeable_days: Decimal
    days: list[DayResult] = field(default_factory=list)


def weekday_index(value: date) -> int:
    """Weekday as Sunday=0 ... Saturday=6.

    THE TRAP: Python's ``date.weekday()`` counts Monday=0 ... Sunday=6, while
    the requirements use Sunday=0 ... Saturday=6. Shifting by one with
    ``(weekday() + 1) % 7`` maps Monday(0)->1 ... Saturday(5)->6, Sunday(6)->0.
    Doing this in ONE helper means the rest of the code never has to think
    about it. (``isoweekday() % 7`` gives the same numbers.)
    """
    return (value.weekday() + 1) % 7


def _normalise_weekend(weekend_days) -> set[int]:
    weekend = {int(day) for day in weekend_days}
    bad = {day for day in weekend if day < 0 or day > 6}
    if bad:
        raise DayCalcError(f"weekend days must be 0..6 (Sunday=0); got {sorted(bad)}.")
    return weekend


def _day_kind(value: date, weekend: set[int], holidays: set[date]) -> DayKind:
    # Weekend wins over holiday, so a day that is both is only removed once.
    if weekday_index(value) in weekend:
        return DayKind.WEEKEND
    if value in holidays:
        return DayKind.HOLIDAY
    return DayKind.WORKING


def calculate_chargeable_days(
    start_date: date,
    end_date: date,
    day_type: DayType | str,
    weekend_days,
    holidays,
) -> DayCalcResult:
    """Chargeable days = calendar days - weekend days - holidays (FR-CAL-4).

    `weekend_days` is a set of ints with Sunday=0 ... Saturday=6.
    `holidays` is a set of dates already filtered for this employee.

    A result of 0 is perfectly valid here; blocking a submission because
    "chargeable days = 0" is the caller's job (Phase 10).
    """
    try:
        day_type = DayType(day_type)
    except ValueError:
        raise DayCalcError(
            f"Unknown day_type '{day_type}'. Use FULL_DAY, FIRST_HALF or SECOND_HALF."
        ) from None

    if end_date < start_date:
        raise DayCalcError(
            f"end_date ({end_date}) must not be before start_date ({start_date})."
        )

    span = (end_date - start_date).days + 1
    if span > MAX_RANGE_DAYS:
        raise DayCalcError(
            f"The range is {span} days long; the maximum is {MAX_RANGE_DAYS}."
        )

    weekend = _normalise_weekend(weekend_days)
    holiday_set = set(holidays)

    if day_type is not DayType.FULL_DAY:
        # A half day is always one single date (D-26).
        if start_date != end_date:
            raise DayCalcError("A half-day leave must start and end on the same date.")
        kind = _day_kind(start_date, weekend, holiday_set)
        chargeable = Decimal("0.5") if kind is DayKind.WORKING else Decimal("0")
        return DayCalcResult(chargeable_days=chargeable, days=[DayResult(start_date, kind)])

    days: list[DayResult] = []
    chargeable = Decimal("0")
    current = start_date
    while current <= end_date:
        kind = _day_kind(current, weekend, holiday_set)
        days.append(DayResult(current, kind))
        if kind is DayKind.WORKING:
            chargeable += Decimal("1")
        current += timedelta(days=1)

    return DayCalcResult(chargeable_days=chargeable, days=days)
