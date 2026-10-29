"""Tests for the pure balance-adjustment rules."""

from decimal import Decimal

import pytest

from app.services.adjustment_rules import (
    AdjustmentError,
    apply_adjustment,
    available_of,
    expected_carried_forward,
    expected_used,
    normalise_field,
    validate_reason,
)


class Balance:
    def __init__(self, allocated="20.00", carried_forward="0.00", used="0.00", pending="0.00"):
        self.allocated = Decimal(allocated)
        self.carried_forward = Decimal(carried_forward)
        self.used = Decimal(used)
        self.pending = Decimal(pending)


def apply(field, delta, **balance):
    return apply_adjustment(Balance(**balance), field, delta)


# --- the happy paths -------------------------------------------------------


def test_increasing_allocated():
    result = apply("ALLOCATED", "5")
    assert result.allocated == Decimal("25.00")
    assert result.available_before == Decimal("20.00")
    assert result.available_after == Decimal("25.00")
    assert result.value_before == Decimal("20.00")
    assert result.value_after == Decimal("25.00")


def test_decreasing_allocated():
    result = apply("ALLOCATED", "-5", used="5.00")
    assert result.allocated == Decimal("15.00")
    assert result.available_after == Decimal("10.00")


@pytest.mark.parametrize(
    ("field", "delta", "attribute", "expected", "used"),
    [
        ("ALLOCATED", "2.50", "allocated", Decimal("22.50"), "0.00"),
        ("CARRIED_FORWARD", "3", "carried_forward", Decimal("3.00"), "0.00"),
        ("USED", "-2", "used", Decimal("0.00"), "2.00"),
        ("USED", "0.5", "used", Decimal("0.50"), "0.00"),
        ("ALLOCATED", "0.01", "allocated", Decimal("20.01"), "0.00"),
        ("ALLOCATED", "-0.01", "allocated", Decimal("19.99"), "0.00"),
    ],
)
def test_every_field_and_exact_decimals(field, delta, attribute, expected, used):
    result = apply(field, delta, used=used)
    assert getattr(result, attribute) == expected


def test_only_the_named_field_changes():
    result = apply("CARRIED_FORWARD", "3", used="4.00")
    assert result.allocated == Decimal("20.00")
    assert result.used == Decimal("4.00")
    assert result.pending == Decimal("0.00")
    assert result.carried_forward == Decimal("3.00")


def test_available_is_recomputed_from_all_four_numbers():
    result = apply("CARRIED_FORWARD", "5", used="10.00", pending="2.00")
    assert result.available_before == Decimal("8.00")
    assert result.available_after == Decimal("13.00")


def test_the_delta_limit_is_inclusive():
    assert apply("ALLOCATED", "365").allocated == Decimal("385.00")
    assert apply("ALLOCATED", "-365", allocated="365.00").allocated == Decimal("0.00")


# --- refusals --------------------------------------------------------------


@pytest.mark.parametrize("delta", ["0", "0.00", "-0.00"])
def test_zero_delta_is_refused(delta):
    with pytest.raises(AdjustmentError) as error:
        apply("ALLOCATED", delta)
    assert error.value.code == "delta_zero"
    assert error.value.http_status == 400


def test_three_decimals_are_refused():
    with pytest.raises(AdjustmentError) as error:
        apply("ALLOCATED", "1.234")
    assert error.value.code == "delta_precision"
    assert error.value.http_status == 400


@pytest.mark.parametrize("delta", ["365.01", "-365.01", "1000"])
def test_a_delta_above_the_limit_is_refused(delta):
    with pytest.raises(AdjustmentError) as error:
        apply("ALLOCATED", delta)
    assert error.value.code == "delta_too_large"
    assert error.value.http_status == 400


def test_pending_can_never_be_adjusted():
    with pytest.raises(AdjustmentError) as error:
        apply("PENDING", "1")
    assert error.value.code == "field_not_allowed"
    assert error.value.http_status == 422


def test_an_unknown_field_is_refused():
    with pytest.raises(AdjustmentError) as error:
        apply("SOMETHING", "1")
    assert error.value.http_status == 422


def test_a_field_cannot_go_below_zero():
    with pytest.raises(AdjustmentError) as error:
        apply("ALLOCATED", "-21")
    assert error.value.code == "field_negative"
    assert error.value.http_status == 409


def test_available_cannot_go_negative_even_if_the_field_stays_positive():
    # allocated 20, used 18 -> reducing allocated to 17 leaves -1 available.
    with pytest.raises(AdjustmentError) as error:
        apply("ALLOCATED", "-3", used="18.00")
    assert error.value.code == "available_negative"
    assert error.value.http_status == 409
    assert "negative" in error.value.message


def test_used_cannot_grow_past_what_is_available():
    with pytest.raises(AdjustmentError) as error:
        apply("USED", "25", allocated="20.00")
    assert error.value.http_status == 409


def test_normalise_field_uppercases_and_trims():
    assert normalise_field(" allocated ") == "ALLOCATED"
    assert normalise_field("carried_forward") == "CARRIED_FORWARD"


# --- the reason ------------------------------------------------------------


def test_a_good_reason_is_trimmed():
    assert validate_reason("  annual bonus days  ") == "annual bonus days"


def test_a_reason_may_contain_a_line_break():
    assert validate_reason("first line\nsecond line") == "first line\nsecond line"


@pytest.mark.parametrize("reason", [None, "", "   ", "abcd"])
def test_a_short_reason_is_refused(reason):
    with pytest.raises(AdjustmentError) as error:
        validate_reason(reason)
    assert error.value.code == "reason_too_short"
    assert error.value.http_status == 422


def test_a_long_reason_is_refused():
    with pytest.raises(AdjustmentError) as error:
        validate_reason("x" * 501)
    assert error.value.code == "reason_too_long"


def test_control_characters_are_refused():
    with pytest.raises(AdjustmentError) as error:
        validate_reason("bad\x00reason")
    assert error.value.code == "reason_control_characters"


def test_exactly_five_and_five_hundred_characters_are_fine():
    assert validate_reason("abcde") == "abcde"
    assert len(validate_reason("y" * 500)) == 500


# --- the invariant helpers -------------------------------------------------


def test_expected_used_adds_the_adjustments():
    assert expected_used("12.00", "2.00") == Decimal("14.00")
    assert expected_used(0, 0) == Decimal("0.00")


def test_expected_carried_forward_adds_the_adjustments():
    assert expected_carried_forward("5.00", "-1.00") == Decimal("4.00")


def test_available_of_matches_the_documented_formula():
    assert available_of("20.00", "5.00", "3.00", "2.00") == Decimal("20.00")
