"""Tests for the pure year-end closing rules (FR-LT-4)."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.closing_rules import (
    Blocker,
    YearView,
    closing_blockers,
    compute_carry,
    find_next_year,
    find_previous_year,
    year_has_ended,
)


def year(year_id, name, start, end, closed=False):
    return YearView(id=year_id, name=name, start_date=start, end_date=end, is_closed=closed)


# --- compute_carry ---------------------------------------------------------


@pytest.mark.parametrize(
    ("remaining", "cap", "expected"),
    [
        (3, 5, (Decimal("3.00"), Decimal("0.00"))),      # below the cap
        (5, 5, (Decimal("5.00"), Decimal("0.00"))),      # exactly the cap
        (12, 5, (Decimal("5.00"), Decimal("7.00"))),     # above the cap
        (0, 5, (Decimal("0.00"), Decimal("0.00"))),      # nothing left
        (2.5, 5, (Decimal("2.50"), Decimal("0.00"))),    # decimals
        (Decimal("0.5"), 5, (Decimal("0.50"), Decimal("0.00"))),
        (12, 0, (Decimal("0.00"), Decimal("12.00"))),    # cap 0: forfeit everything
    ],
)
def test_compute_carry(remaining, cap, expected):
    assert compute_carry(remaining, cap, True) == expected


def test_carry_not_allowed_returns_none():
    assert compute_carry(12, 5, False) is None


def test_a_negative_remaining_is_treated_as_zero():
    assert compute_carry(-3, 5, True) == (Decimal("0.00"), Decimal("0.00"))


@pytest.mark.parametrize(
    ("remaining", "cap"),
    [(12, 5), (3, 5), (0, 5), (2.5, 1), (Decimal("0.5"), 0), (100, 100)],
)
def test_carried_plus_forfeited_always_equals_remaining(remaining, cap):
    carried, forfeited = compute_carry(remaining, cap, True)
    assert carried + forfeited == Decimal(str(remaining))


def test_carry_is_never_above_the_cap():
    carried, _ = compute_carry(999, 5, True)
    assert carried == Decimal("5.00")


# --- adjacent years --------------------------------------------------------


YEARS = [
    year(1, "1997", date(1997, 1, 1), date(1997, 12, 31), closed=True),
    year(2, "1998", date(1998, 1, 1), date(1998, 12, 31)),
    year(3, "1999", date(1999, 1, 1), date(1999, 12, 31)),
    year(4, "2005", date(2005, 1, 1), date(2005, 12, 31)),  # a gap
]


def test_find_next_year_uses_the_adjacent_year():
    assert find_next_year(YEARS[1], YEARS).name == "1999"


def test_find_next_year_returns_none_when_there_is_a_gap():
    assert find_next_year(YEARS[2], YEARS) is None


def test_find_previous_year_uses_the_adjacent_year():
    assert find_previous_year(YEARS[1], YEARS).name == "1997"


def test_find_previous_year_returns_none_when_there_is_a_gap():
    assert find_previous_year(YEARS[0], YEARS) is None


def test_leap_year_boundary_is_adjacent():
    leap = year(9, "2024a", date(2024, 1, 1), date(2024, 2, 28))
    next_year = year(10, "2024b", date(2024, 2, 29), date(2024, 12, 31))
    assert find_next_year(leap, [leap, next_year]).name == "2024b"
    assert find_previous_year(next_year, [leap, next_year]).name == "2024a"


# --- has the year ended ----------------------------------------------------


def test_year_ended_yesterday_and_today():
    end = date(1998, 12, 31)
    assert year_has_ended(date(1999, 1, 1), end) is True
    assert year_has_ended(date(1998, 12, 31), end) is False   # last day: not ended
    assert year_has_ended(date(1998, 12, 30), end) is False


# --- blockers --------------------------------------------------------------


def clean(**overrides):
    values = dict(
        year=YEARS[1],
        today=date(1999, 6, 1),
        next_year=YEARS[2],
        previous_year=YEARS[0],
        pending_request_count=0,
        missing_next_year_assignments=0,
    )
    values.update(overrides)
    return closing_blockers(**values)


def codes(blockers):
    return sorted(blocker.code for blocker in blockers)


def test_a_clean_year_has_no_blockers():
    blockers, warnings = clean()
    assert blockers == [] and warnings == []


def test_already_closed_blocks():
    blockers, _ = clean(year=year(2, "1998", date(1998, 1, 1), date(1998, 12, 31), closed=True))
    assert "already_closed" in codes(blockers)
    assert all(blocker.http_status == 409 for blocker in blockers)


def test_a_year_that_has_not_ended_blocks():
    blockers, _ = clean(today=date(1998, 6, 1))
    assert "not_ended" in codes(blockers)


def test_no_next_year_blocks_and_says_what_to_do():
    blockers, _ = clean(next_year=None)
    assert "no_next_year" in codes(blockers)
    assert "next leave year" in [b for b in blockers if b.code == "no_next_year"][0].message


def test_a_closed_next_year_blocks():
    blockers, _ = clean(next_year=year(3, "1999", date(1999, 1, 1), date(1999, 12, 31), closed=True))
    assert "next_year_closed" in codes(blockers)


def test_a_previous_year_that_is_open_blocks_and_names_it():
    blockers, _ = clean(previous_year=year(1, "1997", date(1997, 1, 1), date(1997, 12, 31)))
    blocker = [b for b in blockers if b.code == "previous_year_open"][0]
    assert "1997" in blocker.message


def test_a_missing_previous_year_is_fine():
    blockers, _ = clean(previous_year=None)
    assert blockers == []


def test_pending_requests_block_with_the_count():
    blockers, _ = clean(pending_request_count=3)
    blocker = [b for b in blockers if b.code == "pending_requests"][0]
    assert "3" in blocker.message


def test_several_blockers_can_appear_together():
    blockers, _ = clean(
        today=date(1998, 6, 1), next_year=None, pending_request_count=2,
        previous_year=year(1, "1997", date(1997, 1, 1), date(1997, 12, 31)),
    )
    assert codes(blockers) == [
        "no_next_year", "not_ended", "pending_requests", "previous_year_open",
    ]


def test_warnings_are_separate_from_blockers():
    blockers, warnings = clean(missing_next_year_assignments=4)
    assert blockers == []
    assert len(warnings) == 1 and "4" in warnings[0]


def test_blocker_is_a_small_value_object():
    blocker = Blocker("x", "message", 409)
    assert (blocker.code, blocker.message, blocker.http_status) == ("x", "message", 409)
