"""Tests for the pure "all must approve" decision rules."""

import pytest

from app.services.approval_rules import (
    APPROVED,
    CANCELLED,
    PENDING,
    REJECTED,
    SKIPPED,
    Action,
    ApprovalError,
    BalanceEffect,
    decide,
)

REQUESTER = 1
A, B, C = 2, 3, 4


def rows(*pairs):
    return list(pairs)


def approve(approvals, actor, requester=REQUESTER, status=PENDING):
    return decide(status, requester, approvals, actor, Action.APPROVE)


def reject(approvals, actor, requester=REQUESTER, status=PENDING):
    return decide(status, requester, approvals, actor, Action.REJECT)


# --- approving -------------------------------------------------------------


def test_single_approver_approves_fully():
    decision = approve(rows((A, PENDING)), A)
    assert decision.actor_approval_status == APPROVED
    assert decision.request_status == APPROVED
    assert decision.balance_effect is BalanceEffect.MOVE_TO_USED
    assert decision.skipped_approver_ids == []


def test_first_of_two_approvers_keeps_it_pending():
    decision = approve(rows((A, PENDING), (B, PENDING)), A)
    assert decision.actor_approval_status == APPROVED
    assert decision.request_status == PENDING
    assert decision.balance_effect is BalanceEffect.NONE


def test_second_of_two_approvers_finishes_it():
    decision = approve(rows((A, APPROVED), (B, PENDING)), B)
    assert decision.request_status == APPROVED
    assert decision.balance_effect is BalanceEffect.MOVE_TO_USED


def test_three_approvers_need_all_three():
    assert approve(rows((A, PENDING), (B, PENDING), (C, PENDING)), A).request_status == PENDING
    assert approve(rows((A, APPROVED), (B, PENDING), (C, PENDING)), B).request_status == PENDING
    decision = approve(rows((A, APPROVED), (B, APPROVED), (C, PENDING)), C)
    assert decision.request_status == APPROVED
    assert decision.balance_effect is BalanceEffect.MOVE_TO_USED


# --- rejecting -------------------------------------------------------------


def test_reject_with_another_pending_skips_it():
    decision = reject(rows((A, PENDING), (B, PENDING)), A)
    assert decision.actor_approval_status == REJECTED
    assert decision.request_status == REJECTED
    assert decision.balance_effect is BalanceEffect.RELEASE
    assert decision.skipped_approver_ids == [B]


def test_reject_after_an_approval_keeps_that_approval_approved():
    decision = reject(rows((A, APPROVED), (B, PENDING)), B)
    assert decision.request_status == REJECTED
    assert decision.balance_effect is BalanceEffect.RELEASE
    assert decision.skipped_approver_ids == []  # A was already APPROVED

    decision = reject(rows((A, APPROVED), (B, PENDING), (C, PENDING)), B)
    assert decision.skipped_approver_ids == [C]


# --- errors ----------------------------------------------------------------


def test_approving_twice_is_refused():
    with pytest.raises(ApprovalError) as error:
        approve(rows((A, APPROVED), (B, PENDING)), A)
    assert error.value.http_status == 409
    assert error.value.code == "already_acted"


@pytest.mark.parametrize("status", [APPROVED, REJECTED, CANCELLED])
def test_acting_on_a_decided_request_is_refused(status):
    with pytest.raises(ApprovalError) as error:
        approve(rows((A, PENDING), (B, PENDING)), A, status=status)
    assert error.value.http_status == 409
    assert error.value.code == "not_pending"


def test_actor_without_a_row_gets_404():
    with pytest.raises(ApprovalError) as error:
        approve(rows((A, PENDING), (B, PENDING)), C)
    assert error.value.http_status == 404
    assert error.value.message == "Leave request not found."


def test_the_requester_cannot_decide_their_own_request():
    with pytest.raises(ApprovalError) as error:
        approve(rows((REQUESTER, PENDING), (B, PENDING)), REQUESTER)
    assert error.value.http_status == 403
    assert error.value.code == "own_request"


def test_a_skipped_approver_cannot_act():
    with pytest.raises(ApprovalError) as error:
        approve(rows((A, SKIPPED), (B, REJECTED)), A)
    assert error.value.http_status == 409
    assert error.value.code == "skipped"


def test_rejecting_twice_is_refused():
    with pytest.raises(ApprovalError) as error:
        reject(rows((A, REJECTED), (B, SKIPPED)), A)
    assert error.value.code == "already_acted"


def test_unknown_action_raises_value_error():
    with pytest.raises(ValueError):
        decide(PENDING, REQUESTER, rows((A, PENDING)), A, "MAYBE")


def test_status_can_be_passed_as_an_enum_like_value():
    class Fake:
        value = PENDING

    assert approve(rows((A, PENDING), (B, Fake())), A).request_status == PENDING
