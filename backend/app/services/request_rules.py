"""Pure leave request overlap and cross-year allocation splitting rules."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.day_calc import DayKind, DayResult, DayType

HALF_DAYS = (DayType.FIRST_HALF, DayType.SECOND_HALF)


class RequestRuleError(ValueError):
    pass


@dataclass(frozen=True)
class RequestRange:
    start_date: date
    end_date: date
    day_type: DayType | str = DayType.FULL_DAY


def _day_type(value: DayType | str) -> DayType:
    return value if isinstance(value, DayType) else DayType(value)


def _year_for(value: date, years):
    return next(
        (year for year in years if year.start_date <= value <= year.end_date),
        None,
    )


def ranges_conflict(a: RequestRange, b: RequestRange) -> bool:
    """Return True if two leave requests overlap on any working interval."""
    if a.start_date > b.end_date or b.start_date > a.end_date:
        return False

    a_type, b_type = _day_type(a.day_type), _day_type(b.day_type)
    same_single_date = a.start_date == a.end_date == b.start_date == b.end_date
    if (
        same_single_date
        and a_type in HALF_DAYS
        and b_type in HALF_DAYS
        and a_type != b_type
    ):
        return False

    return True


def years_for_days(days: list[DayResult], leave_years) -> list:
    years = sorted(leave_years, key=lambda year: year.start_date)
    found: dict[int, object] = {}
    for day in days:
        matched = _year_for(day.date, years)
        if matched is None:
            raise RequestRuleError(f"{day.date} is not inside any leave year.")
        found[matched.id] = matched
    return [found[key] for key in sorted(found)]


def split_days_by_leave_year(
    days: list[DayResult],
    leave_years,
    day_type: DayType | str = DayType.FULL_DAY,
) -> dict[int, Decimal]:
    """Aggregate chargeable working days per leave year."""
    resolved_type = _day_type(day_type)
    weight = Decimal("0.5") if resolved_type in HALF_DAYS else Decimal("1")

    years_for_days(days, leave_years)
    years = sorted(leave_years, key=lambda year: year.start_date)

    per_year: dict[int, Decimal] = {}
    for day in days:
        if day.kind is not DayKind.WORKING:
            continue
        matched = _year_for(day.date, years)
        per_year[matched.id] = per_year.get(matched.id, Decimal("0")) + weight

    return per_year


def split_total(per_year: dict[int, Decimal]) -> Decimal:
    return sum(per_year.values(), Decimal("0"))
