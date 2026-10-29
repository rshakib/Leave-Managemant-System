"""Tests for the pure day-calculation engine (FR-CAL-4).

Everything here is pure: dates in, numbers out. No database, no HTTP.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.day_calc import (
    MAX_RANGE_DAYS,
    DayCalcError,
    DayKind,
    calculate_chargeable_days,
    weekday_index,
)

# Handy names so the tests read clearly (Sunday=0 ... Saturday=6).
SUNDAY, MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY = range(7)

# 2026-10-25 is a Sunday: the anchor for most of these tests.
SUN = date(2026, 10, 25)
MON = date(2026, 10, 26)
TUE = date(2026, 10, 27)
WED = date(2026, 10, 28)
THU = date(2026, 10, 29)
FRI = date(2026, 10, 30)
SAT = date(2026, 10, 31)


def calc(start, end, day_type="FULL_DAY", weekend=frozenset(), holidays=frozenset()):
    return calculate_chargeable_days(start, end, day_type, weekend, holidays)


# --- the weekday numbering trap -------------------------------------------


def test_sunday_is_zero_and_monday_is_one():
    assert weekday_index(SUN) == SUNDAY
    assert weekday_index(MON) == MONDAY
    assert weekday_index(WED) == WEDNESDAY
    assert weekday_index(FRI) == FRIDAY
    assert weekday_index(SAT) == SATURDAY


# --- full days -------------------------------------------------------------


def test_monday_to_friday_with_friday_and_saturday_weekend():
    # Weekend = Friday+Saturday, so the Friday in this range is not chargeable.
    result = calc(MON, FRI, weekend={FRIDAY, SATURDAY})
    assert result.chargeable_days == Decimal("4")
    assert [day.kind for day in result.days] == [
        DayKind.WORKING,
        DayKind.WORKING,
        DayKind.WORKING,
        DayKind.WORKING,
        DayKind.WEEKEND,
    ]


def test_full_mon_fri_working_week():
    result = calc(SUN, THU, weekend={FRIDAY, SATURDAY})
    assert result.chargeable_days == Decimal("5")


def test_range_crossing_a_weekend():
    # Thu, Fri(weekend), Sat(weekend), Sun -> 2 chargeable.
    result = calc(THU, date(2026, 11, 1), weekend={FRIDAY, SATURDAY})
    assert result.chargeable_days == Decimal("2")
    assert [day.kind for day in result.days] == [
        DayKind.WORKING,
        DayKind.WEEKEND,
        DayKind.WEEKEND,
        DayKind.WORKING,
    ]


def test_holiday_in_the_middle():
    result = calc(MON, FRI, weekend={SATURDAY, SUNDAY}, holidays={WED})
    assert result.chargeable_days == Decimal("4")
    assert result.days[2].date == WED
    assert result.days[2].kind is DayKind.HOLIDAY


def test_holiday_on_a_weekend_is_subtracted_once():
    # FRI is a weekend day AND a holiday: it must only be removed once.
    with_holiday = calc(MON, FRI, weekend={FRIDAY, SATURDAY}, holidays={FRI})
    without_holiday = calc(MON, FRI, weekend={FRIDAY, SATURDAY})
    assert with_holiday.chargeable_days == without_holiday.chargeable_days
    assert with_holiday.chargeable_days == Decimal("4")
    assert with_holiday.days[-1].kind is DayKind.WEEKEND


def test_custom_roster_weekend_sunday_and_monday():
    # Sunday+Monday off: Tue, Wed, Thu, Fri, Sat are working = 5.
    result = calc(SUN, SAT, weekend={SUNDAY, MONDAY})
    assert result.chargeable_days == Decimal("5")


def test_range_entirely_of_weekend_days():
    result = calc(FRI, SAT, weekend={FRIDAY, SATURDAY})
    assert result.chargeable_days == Decimal("0")
    assert all(day.kind is DayKind.WEEKEND for day in result.days)


def test_single_day_range():
    result = calc(MON, MON, weekend={SATURDAY, SUNDAY})
    assert result.chargeable_days == Decimal("1")
    assert len(result.days) == 1


def test_range_crossing_a_year_boundary():
    # Tue 29 Dec 2026 .. Sun 3 Jan 2027, weekend Fri+Sat:
    # working = Tue, Wed, Thu, Sun = 4.
    result = calc(date(2026, 12, 29), date(2027, 1, 3), weekend={FRIDAY, SATURDAY})
    assert result.chargeable_days == Decimal("4")
    assert result.days[0].date == date(2026, 12, 29)
    assert result.days[-1].date == date(2027, 1, 3)


# --- half days (D-26) ------------------------------------------------------


def test_half_day_on_a_working_day_is_half():
    result = calc(MON, MON, "FIRST_HALF", weekend={SATURDAY, SUNDAY})
    assert result.chargeable_days == Decimal("0.5")
    assert len(result.days) == 1
    assert result.days[0].kind is DayKind.WORKING


def test_second_half_on_a_working_day_is_half():
    result = calc(MON, MON, "SECOND_HALF", weekend={SATURDAY, SUNDAY})
    assert result.chargeable_days == Decimal("0.5")


def test_half_day_on_a_weekend_is_zero():
    result = calc(SUN, SUN, "FIRST_HALF", weekend={SATURDAY, SUNDAY})
    assert result.chargeable_days == Decimal("0")
    assert result.days[0].kind is DayKind.WEEKEND


def test_half_day_on_a_holiday_is_zero():
    result = calc(MON, MON, "FIRST_HALF", weekend={SATURDAY, SUNDAY}, holidays={MON})
    assert result.chargeable_days == Decimal("0")
    assert result.days[0].kind is DayKind.HOLIDAY


def test_half_day_over_two_dates_raises():
    with pytest.raises(DayCalcError):
        calc(MON, FRI, "FIRST_HALF", weekend={SATURDAY, SUNDAY})


# --- invalid input ---------------------------------------------------------


def test_end_before_start_raises():
    with pytest.raises(DayCalcError):
        calc(FRI, MON)


def test_range_longer_than_the_maximum_raises():
    too_long = date(2026, 1, 1) + timedelta(days=MAX_RANGE_DAYS)
    assert (too_long - date(2026, 1, 1)).days + 1 == MAX_RANGE_DAYS + 1
    with pytest.raises(DayCalcError):
        calc(date(2026, 1, 1), too_long)


def test_range_exactly_at_the_maximum_is_allowed():
    last = date(2026, 1, 1) + timedelta(days=MAX_RANGE_DAYS - 1)
    result = calc(date(2026, 1, 1), last, weekend={FRIDAY, SATURDAY})
    assert result.chargeable_days > 0


def test_unknown_day_type_raises():
    with pytest.raises(DayCalcError):
        calc(MON, MON, "HALF_DAY")


def test_weekend_day_out_of_range_raises():
    with pytest.raises(DayCalcError):
        calc(MON, MON, weekend={7})


# --- the per-day list ------------------------------------------------------


def test_per_day_list_is_complete_and_in_order():
    result = calc(MON, FRI, weekend={SATURDAY, SUNDAY}, holidays={WED})
    assert [day.date for day in result.days] == [MON, TUE, WED, THU, FRI]
    assert [day.kind for day in result.days] == [
        DayKind.WORKING,
        DayKind.WORKING,
        DayKind.HOLIDAY,
        DayKind.WORKING,
        DayKind.WORKING,
    ]
