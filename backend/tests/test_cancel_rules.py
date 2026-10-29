"""Tests for the pure cancellation rules (FR-LR-5 / Open Question #1, D-194).

Rules under test:
  * PENDING   → requester or admin, releases the reserved days.
  * APPROVED  → admin only, restores the used days.
  * REJECTED/CANCELLED → nobody.
  * a closed leave year → never (the service raises 409).
"""

import pytest

from app.services.cancel_rules import (
    APPROVED,
    CANCELLED,
    PENDING,
    REJECTED,
    SKIPPED,
    BalanceEffect,
    CancelError,
    can_cancel,
    closed_year_error,
    decide_cancel,
)

REQUESTER = 1
ADMIN = 2
APPROVER = 3
STRANGER = 4


def cancel(
    status=PENDING,
    requester=REQUESTER,
    actor=REQUESTER,
    is_admin=False,
    can_see=True,
    approvals=((APPROVER, PENDING),),
    comment=None,
):
    return decide_cancel(status, requester, actor, is_admin, can_see, list(approvals), comment)


# --- the happy paths -------------------------------------------------------


def test_requester_cancels_their_pending_request():
    decision = cancel()
    assert decision.balance_effect is BalanceEffect.RELEASE
    assert decision.skipped_approver_ids == [APPROVER]
    assert decision.comment is None


def test_requester_may_add_an_optional_comment():
    assert cancel(comment="  changed my plans  ").comment == "changed my plans"


def test_admin_can_cancel_their_own_pending_request():
    decision = cancel(
        requester=ADMIN,
        actor=ADMIN,
        is_admin=True,
        comment="my own leave",
    )
    assert decision.balance_effect is BalanceEffect.RELEASE


def test_an_admin_can_cancel_an_approved_request_and_used_days_are_restored():
    """Open Question #1: once approved, only an administrator can undo it."""
    decision = cancel(
        status=APPROVED,
        actor=ADMIN,
        is_admin=True,
        approvals=((APPROVER, APPROVED),),
        comment="wrong dates entered",
    )
    assert decision.balance_effect is BalanceEffect.RESTORE_USED
    assert decision.comment == "wrong dates entered"
    # Nothing is left waiting for a decision on an approved request.
    assert decision.skipped_approver_ids == []


def test_only_pending_approvals_become_skipped():
    decision = cancel(
        approvals=((APPROVER, APPROVED), (10, PENDING), (11, SKIPPED))
    )
    assert decision.skipped_approver_ids == [10]


def test_an_approved_request_never_skips_approvals():
    decision = cancel(
        status=APPROVED,
        actor=ADMIN,
        is_admin=True,
        approvals=((APPROVER, APPROVED), (10, PENDING)),
        comment="undo",
    )
    assert decision.skipped_approver_ids == []


# --- who may NOT cancel ----------------------------------------------------


def test_stranger_gets_404():
    with pytest.raises(CancelError) as error:
        cancel(actor=STRANGER, can_see=False)
    assert error.value.http_status == 404
    assert error.value.message == "Leave request not found."


def test_an_assigned_approver_gets_403():
    with pytest.raises(CancelError) as error:
        cancel(actor=APPROVER, can_see=True)
    assert error.value.http_status == 403
    assert error.value.code == "forbidden"


def test_the_requester_cannot_cancel_an_approved_request():
    """The employee may withdraw a request only while it is still pending."""
    with pytest.raises(CancelError) as error:
        cancel(status=APPROVED, actor=REQUESTER)
    assert error.value.http_status == 403
    assert error.value.code == "forbidden"
    assert "administrator" in error.value.message.lower()


def test_an_approver_cannot_cancel_an_approved_request():
    with pytest.raises(CancelError) as error:
        cancel(status=APPROVED, actor=APPROVER)
    assert error.value.http_status == 403


@pytest.mark.parametrize("status", [REJECTED, CANCELLED])
def test_a_finished_request_cannot_be_cancelled(status):
    with pytest.raises(CancelError) as error:
        cancel(status=status, actor=ADMIN, is_admin=True, comment="too late")
    assert error.value.http_status == 409
    assert error.value.code == "not_cancellable"


def test_an_unknown_status_is_refused():
    with pytest.raises(CancelError) as error:
        cancel(status="WEIRD", actor=ADMIN, is_admin=True, comment="hmm")
    assert error.value.http_status == 409


# --- the reason an admin must give ----------------------------------------


@pytest.mark.parametrize("comment", [None, "", "  ", "hi"])
def test_admin_needs_a_real_reason(comment):
    with pytest.raises(CancelError) as error:
        cancel(actor=ADMIN, is_admin=True, comment=comment)
    assert error.value.http_status == 400
    assert error.value.code == "comment_required"


@pytest.mark.parametrize("status", [PENDING, APPROVED])
def test_the_reason_is_required_for_both_admin_cancellations(status):
    with pytest.raises(CancelError) as error:
        cancel(status=status, actor=ADMIN, is_admin=True, comment=None)
    assert error.value.code == "comment_required"


def test_admin_reason_is_trimmed_before_the_length_check():
    with pytest.raises(CancelError):
        cancel(actor=ADMIN, is_admin=True, comment="  a  ")
    assert cancel(actor=ADMIN, is_admin=True, comment="  abc  ").comment == "abc"


def test_a_comment_longer_than_1000_is_refused():
    with pytest.raises(CancelError) as error:
        cancel(comment="x" * 1001)
    assert error.value.http_status == 400
    assert error.value.code == "comment_too_long"


# --- the UI flag ----------------------------------------------------------


def test_can_cancel_matches_the_rule_for_pending_requests():
    assert can_cancel(PENDING, REQUESTER, REQUESTER, False) is True
    assert can_cancel(PENDING, REQUESTER, ADMIN, True) is True
    assert can_cancel(PENDING, REQUESTER, APPROVER, False) is False


def test_can_cancel_for_approved_requests_is_admin_only():
    assert can_cancel(APPROVED, REQUESTER, ADMIN, True) is True
    assert can_cancel(APPROVED, REQUESTER, REQUESTER, False) is False
    assert can_cancel(APPROVED, REQUESTER, APPROVER, False) is False


@pytest.mark.parametrize("status", [REJECTED, CANCELLED, "WEIRD"])
def test_can_cancel_is_false_for_finished_requests(status):
    assert can_cancel(status, REQUESTER, REQUESTER, False) is False
    assert can_cancel(status, REQUESTER, ADMIN, True) is False


@pytest.mark.parametrize("status", [PENDING, APPROVED])
def test_a_closed_leave_year_always_answers_false(status):
    assert can_cancel(status, REQUESTER, ADMIN, True, touches_closed_year=True) is False


def test_the_closed_year_error_names_the_year_and_is_a_409():
    blocker = closed_year_error(["2099", "2098"])
    assert blocker.http_status == 409
    assert blocker.code == "closed_year"
    assert "2098, 2099" in blocker.message
    assert "adjustment" in blocker.message


def test_status_can_be_an_enum_like_value():
    class Fake:
        value = PENDING

    assert cancel(status=Fake()).balance_effect is BalanceEffect.RELEASE
