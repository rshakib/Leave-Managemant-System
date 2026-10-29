"""Pure rules for year-end closing and carry-forward (FR-LT-4).

No database, no clock: the caller passes `today` in. Everything here is decided
from plain values so it can be unit-tested without a database.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class Blocker:
    """Something that makes closing impossible right now."""

    code: str
    message: str
    http_status: int


@dataclass(frozen=True)
class YearView:
    """The little bit of a leave year the rules need (real rows duck-type this)."""

    id: int
    name: str
    start_date: date
    end_date: date
    is_closed: bool = False


def _days(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def compute_carry(
    remaining, max_carry_forward_days, carry_allowed: bool
) -> tuple[Decimal, Decimal] | None:
    """Split what is left at year end into (carried, forfeited).

    Returns **None** when the leave type does not allow carry-forward — in that
    case no log row is written at all (DECISIONS D-22).
    """
    if not carry_allowed:
        return None

    left = _days(remaining)
    if left < 0:  # a remaining balance is never negative
        left = Decimal("0.00")

    cap = _days(max_carry_forward_days)
    if cap < 0:
        cap = Decimal("0.00")

    carried = left if left <= cap else cap
    forfeited = left - carried
    return carried, forfeited


def find_next_year(from_year, years) -> object | None:
    """The ADJACENT year only: it must start the day after this one ends."""
    target = from_year.end_date + timedelta(days=1)
    for year in years:
        if year.id == from_year.id:
            continue
        if year.start_date == target:
            return year
    return None


def find_previous_year(from_year, years) -> object | None:
    """The ADJACENT previous year: it must end the day before this one starts."""
    target = from_year.start_date - timedelta(days=1)
    for year in years:
        if year.id == from_year.id:
            continue
        if year.end_date == target:
            return year
    return None


def year_has_ended(today: date, end_date: date) -> bool:
    """True only once `today` is past the last day of the year."""
    return today > end_date


def closing_blockers(
    *,
    year,
    today: date,
    next_year,
    previous_year,
    pending_request_count: int,
    missing_next_year_assignments: int = 0,
) -> tuple[list[Blocker], list[str]]:
    """Return (blockers, warnings). Warnings never stop a closing."""
    blockers: list[Blocker] = []

    if year.is_closed:
        blockers.append(
            Blocker(
                "already_closed",
                f"Leave year '{year.name}' is already closed.",
                409,
            )
        )
    if not year_has_ended(today, year.end_date):
        blockers.append(
            Blocker(
                "not_ended",
                f"Leave year '{year.name}' ends on {year.end_date.isoformat()} "
                "and can only be closed after that date.",
                409,
            )
        )
    if next_year is None:
        blockers.append(
            Blocker(
                "no_next_year",
                "There is no leave year starting the day after this one ends. "
                "Create the next leave year first (its dates must be adjacent).",
                409,
            )
        )
    elif next_year.is_closed:
        blockers.append(
            Blocker(
                "next_year_closed",
                f"The next leave year '{next_year.name}' is already closed.",
                409,
            )
        )
    if previous_year is not None and not previous_year.is_closed:
        blockers.append(
            Blocker(
                "previous_year_open",
                f"The previous leave year '{previous_year.name}' is not closed "
                "yet. Close it first, so days are carried forward in order.",
                409,
            )
        )
    if pending_request_count:
        blockers.append(
            Blocker(
                "pending_requests",
                f"{pending_request_count} request(s) in this leave year are still "
                "pending. Approve, reject or cancel them first.",
                409,
            )
        )

    warnings: list[str] = []
    if missing_next_year_assignments:
        warnings.append(
            f"{missing_next_year_assignments} employee(s) have days to carry "
            "forward but no leave-type assignment in the next year. The carried "
            "days are still added to their balance."
        )
    return blockers, warnings
