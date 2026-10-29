"""Tests for the pure leave-request rules (overlap + cross-year split)."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.services.day_calc import DayKind, calculate_chargeable_days
from app.services.request_rules import (
    RequestRange,
    RequestRuleError,
    ranges_conflict,
    split_days_by_leave_year,
    split_total,
)

FRIDAY, SATURDAY = 5, 6
WEEKEND = {FRIDAY, SATURDAY}


@dataclass(frozen=True)
class Year:
    id: int
    start_date: date
    end_date: date


YEAR_2098 = Year(1, date(2098, 1, 1), date(2098, 12, 31))
YEAR_2099 = Year(2, date(2099, 1, 1), date(2099, 12, 31))
YEARS = [YEAR_2098, YEAR_2099]


def split(start, end, day_type="FULL_DAY", holidays=frozenset()):
    result = calculate_chargeable_days(start, end, day_type, WEEKEND, holidays)
    per_year = split_days_by_leave_year(result.days, YEARS, day_type)
    return result, per_year


# --- overlap (D-09) --------------------------------------------------------


def test_identical_ranges_conflict():
    a = RequestRange(date(2099, 3, 1), date(2099, 3, 5))
    assert ranges_conflict(a, a)


def test_ranges_touching_at_one_date_conflict():
    a = RequestRange(date(2099, 3, 1), date(2099, 3, 5))
    b = RequestRange(date(2099, 3, 5), date(2099, 3, 9))
    assert ranges_conflict(a, b)


def test_contained_range_conflicts():
    outer = RequestRange(date(2099, 3, 1), date(2099, 3, 10))
    inner = RequestRange(date(2099, 3, 3), date(2099, 3, 4))
    assert ranges_conflict(outer, inner)


def test_adjacent_days_do_not_conflict():
    a = RequestRange(date(2099, 3, 1), date(2099, 3, 5))
    b = RequestRange(date(2099, 3, 6), date(2099, 3, 9))
    assert not ranges_conflict(a, b)


def test_two_different_halves_on_the_same_date_do_not_conflict():
    morning = RequestRange(date(2099, 3, 1), date(2099, 3, 1), "FIRST_HALF")
    afternoon = RequestRange(date(2099, 3, 1), date(2099, 3, 1), "SECOND_HALF")
    assert not ranges_conflict(morning, afternoon)


def test_the_same_half_twice_conflicts():
    morning = RequestRange(date(2099, 3, 1), date(2099, 3, 1), "FIRST_HALF")
    assert ranges_conflict(morning, morning)


def test_full_day_against_a_half_day_conflicts():
    full = RequestRange(date(2099, 3, 1), date(2099, 3, 1), "FULL_DAY")
    half = RequestRange(date(2099, 3, 1), date(2099, 3, 1), "FIRST_HALF")
    assert ranges_conflict(full, half)


def test_halves_on_different_dates_are_compared_by_range():
    monday_am = RequestRange(date(2099, 3, 2), date(2099, 3, 2), "FIRST_HALF")
    tuesday_pm = RequestRange(date(2099, 3, 3), date(2099, 3, 3), "SECOND_HALF")
    assert not ranges_conflict(monday_am, tuesday_pm)


# --- splitting (D-05) ------------------------------------------------------


def test_split_inside_one_year():
    result, per_year = split(date(2099, 3, 2), date(2099, 3, 6))
    # Mon..Fri, weekend Fri+Sat -> Mon, Tue, Wed, Thu = 4.
    assert result.chargeable_days == Decimal("4")
    assert per_year == {2: Decimal("4")}


def test_split_across_a_year_boundary():
    # Mon 29 Dec 2098 .. Sat 3 Jan 2099, weekend Fri+Sat:
    # working = 29, 30, 31 Dec + 1 Jan = 4.
    result, per_year = split(date(2098, 12, 29), date(2099, 1, 3))
    assert result.chargeable_days == Decimal("4")
    assert per_year == {1: Decimal("3"), 2: Decimal("1")}
    assert split_total(per_year) == result.chargeable_days


def test_split_with_a_holiday_on_the_boundary():
    # New Year's Day is a holiday, so 2099 gets no chargeable days at all.
    result, per_year = split(
        date(2098, 12, 29), date(2099, 1, 3), holidays={date(2099, 1, 1)}
    )
    assert result.chargeable_days == Decimal("3")
    assert per_year == {1: Decimal("3")}
    assert split_total(per_year) == result.chargeable_days


def test_split_of_a_half_day():
    result, per_year = split(date(2099, 3, 2), date(2099, 3, 2), "FIRST_HALF")
    assert result.chargeable_days == Decimal("0.5")
    assert per_year == {2: Decimal("0.5")}


def test_split_of_a_half_day_on_the_last_day_of_a_year():
    # 31 Dec 2098 is a Wednesday, so it is a working day.
    result, per_year = split(date(2098, 12, 31), date(2098, 12, 31), "SECOND_HALF")
    assert result.chargeable_days == Decimal("0.5")
    assert per_year == {1: Decimal("0.5")}


def test_date_outside_every_leave_year_raises():
    with pytest.raises(RequestRuleError) as error:
        split(date(2100, 1, 1), date(2100, 1, 2))
    assert "2100-01-01" in str(error.value)


def test_split_sum_matches_chargeable_days():
    for start, end in [
        (date(2099, 3, 2), date(2099, 3, 6)),
        (date(2098, 12, 29), date(2099, 1, 3)),
        (date(2099, 6, 1), date(2099, 6, 30)),
    ]:
        result, per_year = split(start, end)
        assert split_total(per_year) == result.chargeable_days


def test_weekend_only_range_splits_to_nothing():
    # Fri 2 Jan 2099 .. Sat 3 Jan 2099: both are weekend days.
    result, per_year = split(date(2099, 1, 2), date(2099, 1, 3))
    assert result.chargeable_days == Decimal("0")
    assert per_year == {}
    assert split_total(per_year) == Decimal("0")


def test_only_working_days_count():
    result, per_year = split(date(2099, 3, 2), date(2099, 3, 8))
    working = [day for day in result.days if day.kind is DayKind.WORKING]
    assert split_total(per_year) == Decimal(len(working))
