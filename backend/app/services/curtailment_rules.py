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
    original_day_type: str = "FULL_DAY",
    curtailed_day_type: str = "FULL_DAY",
) -> None:
    """Validate that the curtailed end date and day type are valid.

    - Must be on or after start_date.
    - Must be on or before original_end_date.
    - If curtailed_end_date == original_end_date, it is ONLY valid if original was FULL_DAY and curtailed is half day (FIRST_HALF or SECOND_HALF).
    """
    if curtailed_end_date < start_date:
        raise CurtailmentRuleError(
            f"Curtailed end date ({curtailed_end_date}) cannot be before the start date ({start_date}).",
            400,
        )
    if curtailed_end_date > original_end_date:
        raise CurtailmentRuleError(
            f"Curtailed end date ({curtailed_end_date}) cannot be after the original end date ({original_end_date}).",
            400,
        )
    if curtailed_end_date == original_end_date:
        if not (original_day_type == "FULL_DAY" and curtailed_day_type in ("FIRST_HALF", "SECOND_HALF")):
            raise CurtailmentRuleError(
                f"Curtailed end date must be before the original end date ({original_end_date}), or select half-day for a single day leave.",
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
    is_curtailable: bool = True,
) -> tuple[bool, Optional[str]]:
    """Determine whether an employee can submit an early return request."""
    if request_status != "APPROVED":
        return False, f"Only approved requests can be curtailed (status is {request_status})."
    if touches_closed_year:
        return False, "Cannot curtail a leave request touching a closed leave year."
    if has_pending_curtailment:
        return False, "An early return request is already pending decision for this leave request."
    if not is_curtailable:
        return False, "This leave request cannot be reduced further (already a half day)."
    return True, None
