from datetime import date
from decimal import Decimal
import pytest

from app.services.curtailment_rules import (
    CurtailmentRuleError,
    calculate_curtailment_refund,
    can_request_curtailment,
    validate_curtailment_dates,
)


def test_validate_curtailment_dates_valid():
    start = date(2026, 11, 1)
    end = date(2026, 11, 5)
    curtailed = date(2026, 11, 2)
    # Should not raise
    validate_curtailment_dates(start, end, curtailed)

    # Returning on same day as start date (1 day / same day return) is valid if original end > start
    validate_curtailment_dates(start, end, start)


def test_validate_curtailment_dates_before_start():
    start = date(2026, 11, 2)
    end = date(2026, 11, 5)
    with pytest.raises(CurtailmentRuleError, match="cannot be before the start date"):
        validate_curtailment_dates(start, end, date(2026, 11, 1))


def test_validate_curtailment_dates_equal_or_after_end():
    start = date(2026, 11, 1)
    end = date(2026, 11, 5)
    with pytest.raises(CurtailmentRuleError, match="must be strictly before"):
        validate_curtailment_dates(start, end, end)

    with pytest.raises(CurtailmentRuleError, match="must be strictly before"):
        validate_curtailment_dates(start, end, date(2026, 11, 6))


def test_calculate_curtailment_refund():
    # 3 days originally approved, returns after 1 day -> 2 days refunded
    refund = calculate_curtailment_refund(Decimal("3.00"), Decimal("1.00"))
    assert refund == Decimal("2.00")

    # 1.00 day approved, returns after 0.5 day (half day) -> 0.5 refunded
    refund_half = calculate_curtailment_refund(Decimal("1.00"), Decimal("0.50"))
    assert refund_half == Decimal("0.50")

    # Fractional calculations (e.g. 2.5 down to 1.0)
    assert calculate_curtailment_refund(Decimal("2.50"), Decimal("1.00")) == Decimal("1.50")


def test_calculate_curtailment_refund_invalid():
    with pytest.raises(CurtailmentRuleError, match="must be less than original days"):
        calculate_curtailment_refund(Decimal("2.00"), Decimal("2.00"))

    with pytest.raises(CurtailmentRuleError, match="must be less than original days"):
        calculate_curtailment_refund(Decimal("2.00"), Decimal("3.00"))

    with pytest.raises(CurtailmentRuleError, match="cannot be negative"):
        calculate_curtailment_refund(Decimal("2.00"), Decimal("-1.00"))


def test_can_request_curtailment():
    ok, err = can_request_curtailment("APPROVED")
    assert ok is True
    assert err is None

    ok, err = can_request_curtailment("PENDING")
    assert ok is False
    assert "Only approved requests" in err

    ok, err = can_request_curtailment("CANCELLED")
    assert ok is False
    assert "Only approved requests" in err

    ok, err = can_request_curtailment("REJECTED")
    assert ok is False
    assert "Only approved requests" in err

    ok, err = can_request_curtailment("APPROVED", touches_closed_year=True)
    assert ok is False
    assert "closed leave year" in err

    ok, err = can_request_curtailment("APPROVED", has_pending_curtailment=True)
    assert ok is False
    assert "already pending" in err
