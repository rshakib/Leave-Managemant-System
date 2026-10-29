"""Pure rules for leave assignment removal, Annual Leave transfer, and reassignment."""

from decimal import Decimal
from typing import Optional


class AssignmentError(ValueError):
    """Raised when an assignment removal or reassignment operation violates business rules."""


def validate_removal(
    *,
    leave_type_code: str,
    pending: Decimal,
    used: Decimal,
    al_allocated: Optional[Decimal] = None,
    al_carried_forward: Optional[Decimal] = None,
    al_used: Optional[Decimal] = None,
    al_pending: Optional[Decimal] = None,
) -> Decimal:
    """Validate whether a leave assignment can be removed.

    Returns the number of used days to transfer to Annual Leave (AL).
    Raises AssignmentError if the removal is not permitted.
    """
    if pending > Decimal("0"):
        raise AssignmentError(
            f"Cannot remove assignment: employee has {pending} day(s) pending approval for this leave type. Please decide or cancel those requests first."
        )

    if used <= Decimal("0"):
        return Decimal("0.00")

    if leave_type_code == "AL":
        raise AssignmentError(
            "Cannot remove Annual Leave (AL) assignment when days have already been used."
        )

    if al_allocated is None:
        raise AssignmentError(
            f"Cannot remove assignment: Employee has used {used} day(s), but no Annual Leave (AL) assignment exists to transfer them to."
        )

    al_cf = al_carried_forward or Decimal("0")
    al_u = al_used or Decimal("0")
    al_p = al_pending or Decimal("0")
    al_available = (al_allocated + al_cf) - (al_u + al_p)

    if al_available < used:
        raise AssignmentError(
            f"Cannot remove assignment: transferring {used} used day(s) to Annual Leave would exceed available Annual Leave (available: {al_available})."
        )

    return used


def calculate_reassignment(
    *,
    transferred_days: Decimal,
    al_used: Decimal,
) -> tuple[Decimal, Decimal]:
    """Calculate the restored used days and new AL used days upon reassignment.

    Returns (restored_used, new_al_used).
    """
    restored_used = transferred_days
    new_al_used = max(Decimal("0.00"), al_used - transferred_days)
    return restored_used, new_al_used

