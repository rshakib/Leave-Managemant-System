"""Pure rules about leave requests: overlap detection and cross-year splitting.

No database, no HTTP, no clock — so both the preview and the real submission can
call the exact same code and can never disagree.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.day_calc import DayKind, DayResult, DayType

HALF_DAYS = (DayType.FIRST_HALF, DayType.SECOND_HALF)


class RequestRuleError(ValueError):
    """Raised when a rule about ranges/splitting cannot be satisfied."""


@dataclass(frozen=True)
class RequestRange:
    """The minimum needed to decide whether two requests overlap."""

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
    """True when two requests want the same calendar days (D-09).

    Inclusive ranges overlap when `a.start <= b.end and b.start <= a.end`.
    The one exception: two HALF-day requests on the SAME single date in
    DIFFERENT halves (first half + second half) fit together. Everything else
    conflicts — including the same half twice, and a full day against any half.
    """
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
    """Every leave year the range touches, in date order.

    Raises `RequestRuleError` naming the first date that sits outside all years.
    """
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
    """Split the per-day list across leave years (D-05).

    `leave_years` are objects with `id`, `start_date` and `end_date`.
    `day_type` is needed because a half day's single WORKING day is worth 0.5,
    not 1.0 — the per-day list alone cannot tell those apart.

    Every date in the range must sit inside some leave year. Years with zero
    chargeable days are omitted (an allocation row must be > 0 days).
    """
    resolved_type = _day_type(day_type)
    weight = Decimal("0.5") if resolved_type in HALF_DAYS else Decimal("1")

    # Validates coverage too: raises if a date is outside every leave year.
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
    """The sum of the parts — must equal the request's chargeable days."""
    return sum(per_year.values(), Decimal("0"))
