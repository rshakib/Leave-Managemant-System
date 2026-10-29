"""Pure business rules for early return / leave curtailment.

No database, no network, no side effects — purely deterministic logic.
"""

from datetime import date
from decimal import Decimal
from typing import Optional


class CurtailmentRuleError(Exception):
    def __init__(self, message: str, http_status: int = 400):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


def validate_curtailment_dates(
    start_date: date,
    original_end_date: date,
    curtailed_end_date: date,
) -> None:
    """Validate that the curtailed end date is within a valid range.

    Must be on or after the original start date, and strictly before the original end date.
    """
    if curtailed_end_date < start_date:
        raise CurtailmentRuleError(
            f"Curtailed end date ({curtailed_end_date}) cannot be before the start date ({start_date}).",
            400,
        )
    if curtailed_end_date >= original_end_date:
        raise CurtailmentRuleError(
            f"Curtailed end date ({curtailed_end_date}) must be strictly before the original end date ({original_end_date}).",
            400,
        )


def calculate_curtailment_refund(
    original_days: Decimal,
    new_days: Decimal,
) -> Decimal:
    """Calculate the number of days to refund to the employee's balance."""
    orig = Decimal(str(original_days))
    new = Decimal(str(new_days))
    if new < 0:
        raise CurtailmentRuleError("New chargeable days cannot be negative.", 400)
    if new >= orig:
        raise CurtailmentRuleError(
            f"New chargeable days ({new}) must be less than original days ({orig}) to qualify for early return refund.",
            400,
        )
    refund = orig - new
    if refund <= Decimal("0"):
        raise CurtailmentRuleError("Early return must refund at least some portion of a day.", 400)
    return refund


def can_request_curtailment(
    request_status: str,
    touches_closed_year: bool = False,
    has_pending_curtailment: bool = False,
) -> tuple[bool, Optional[str]]:
    """Determine whether an employee can submit an early return request."""
    if request_status != "APPROVED":
        return False, f"Only approved requests can be curtailed (status is {request_status})."
    if touches_closed_year:
        return False, "Cannot curtail a leave request touching a closed leave year."
    if has_pending_curtailment:
        return False, "An early return request is already pending decision for this leave request."
    return True, None
