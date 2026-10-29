"""Tests for leave assignment removal, Annual Leave transfer, and reassignment rules."""

from decimal import Decimal
import pytest

from app.services.assignment_rules import (
    AssignmentError,
    calculate_reassignment,
    validate_removal,
)


def test_validate_removal_zero_used_no_pending():
    """Unused assignment can be removed without touching AL."""
    transferred = validate_removal(
        leave_type_code="CL",
        pending=Decimal("0.00"),
        used=Decimal("0.00"),
    )
    assert transferred == Decimal("0.00")


def test_validate_removal_blocks_if_pending_requests():
    """Removal is blocked if there are pending leave requests."""
    with pytest.raises(AssignmentError, match="pending approval"):
        validate_removal(
            leave_type_code="CL",
            pending=Decimal("2.00"),
            used=Decimal("0.00"),
        )


def test_validate_removal_blocks_al_if_used():
    """Cannot remove Annual Leave itself if it has used days."""
    with pytest.raises(AssignmentError, match="Cannot remove Annual Leave"):
        validate_removal(
            leave_type_code="AL",
            pending=Decimal("0.00"),
            used=Decimal("3.00"),
            al_allocated=Decimal("15.00"),
            al_used=Decimal("3.00"),
        )


def test_validate_removal_requires_al_balance():
    """Cannot remove used leave if employee has no Annual Leave balance."""
    with pytest.raises(AssignmentError, match="no Annual Leave.*exists"):
        validate_removal(
            leave_type_code="CL",
            pending=Decimal("0.00"),
            used=Decimal("3.00"),
            al_allocated=None,
        )


def test_validate_removal_blocks_if_insufficient_al():
    """Cannot remove used leave if AL does not have enough available days to absorb."""
    with pytest.raises(AssignmentError, match="would exceed available Annual Leave"):
        validate_removal(
            leave_type_code="CL",
            pending=Decimal("0.00"),
            used=Decimal("5.00"),
            al_allocated=Decimal("10.00"),
            al_carried_forward=Decimal("0.00"),
            al_used=Decimal("8.00"),  # Only 2 days available
            al_pending=Decimal("0.00"),
        )


def test_validate_removal_success_transfers_used_days():
    """Valid removal returns used days to transfer."""
    transferred = validate_removal(
        leave_type_code="CL",
        pending=Decimal("0.00"),
        used=Decimal("3.00"),
        al_allocated=Decimal("10.00"),
        al_carried_forward=Decimal("2.00"),
        al_used=Decimal("4.00"),  # Available: 12 - 4 = 8 days >= 3 days
        al_pending=Decimal("0.00"),
    )
    assert transferred == Decimal("3.00")


def test_calculate_reassignment_restores_used_and_refunds_al():
    """Reassigning restores the used count and refunds Annual Leave."""
    transferred_days = Decimal("3.00")
    al_used = Decimal("7.00")  # includes the 3.00 transferred previously

    restored_used, new_al_used = calculate_reassignment(
        transferred_days=transferred_days,
        al_used=al_used,
    )
    assert restored_used == Decimal("3.00")
    assert new_al_used == Decimal("4.00")  # 7.00 - 3.00 = 4.00


def test_calculate_reassignment_clamps_al_at_zero():
    """AL used days cannot drop below zero even with discrepancies."""
    restored_used, new_al_used = calculate_reassignment(
        transferred_days=Decimal("5.00"),
        al_used=Decimal("2.00"),
    )
    assert restored_used == Decimal("5.00")
    assert new_al_used == Decimal("0.00")

