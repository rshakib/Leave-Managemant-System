"""Cancellation rules, as a PURE function (FR-LR-5 / Open Question #1, D-194).

Who may cancel what:

* **PENDING**   — the employee who asked, **or** an administrator. The reserved
  days are released (`pending -= days`).
* **APPROVED**  — an **administrator only**. The days that were counted as used
  are restored (`used -= days`), because the leave is being undone.
* **REJECTED / CANCELLED** — nobody.

A request that touches a **closed leave year** can never be cancelled: that
year's balance may already have been carried forward, so the service refuses
with 409 and nothing moves (see `closed_year_error`).

DECISIONS D-194 supersedes D-153, which had made an approved request final.
"""

from dataclasses import dataclass, field
from enum import Enum

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
SKIPPED = "SKIPPED"


class BalanceEffect(str, Enum):
    NONE = "NONE"
    # A pending request: the reservation goes back to `available`.
    RELEASE = "RELEASE"
    # An approved request: the days leave `used` and go back to `available`.
    RESTORE_USED = "RESTORE_USED"


class CancelError(Exception):
    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class CancelDecision:
    skipped_approver_ids: list[int] = field(default_factory=list)
    balance_effect: BalanceEffect = BalanceEffect.NONE
    comment: str | None = None


def _text(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def closed_year_error(names: list[str]) -> CancelError:
    """The refusal used when a cancellation would touch a closed leave year."""
    listed = ", ".join(sorted(names))
    return CancelError(
        "closed_year",
        f"This request touches the closed leave year(s) {listed}, so its days "
        "cannot be moved back. Nothing was changed; an administrator can correct "
        "the balance with a manual adjustment instead.",
        409,
    )


def decide_cancel(
    request_status,
    requester_id: int,
    actor_id: int,
    actor_is_admin: bool,
    actor_can_see_request: bool,
    approvals: list[tuple[int, object]],
    comment: str | None,
) -> CancelDecision:
    status = _text(request_status)
    reason = (comment or "").strip() or None
    is_requester = actor_id == requester_id

    # A stranger sees the same 404 as a missing request (no existence leak).
    if not actor_can_see_request:
        raise CancelError("not_found", "Leave request not found.", 404)

    if status in (REJECTED, CANCELLED):
        raise CancelError(
            "not_cancellable", f"This request is already {status.lower()}.", 409
        )

    if status == APPROVED:
        # Approved leave is undone by an ADMIN only (Open Question #1).
        if not actor_is_admin:
            raise CancelError(
                "forbidden",
                "An approved request can only be cancelled by an administrator.",
                403,
            )
    elif status == PENDING:
        # Someone who can see it but is neither the requester nor an admin
        # (typically an assigned approver) may not cancel it.
        if not (is_requester or actor_is_admin):
            raise CancelError(
                "forbidden",
                "Only the employee who asked for this leave, or an administrator, "
                "can cancel it.",
                403,
            )
    else:
        raise CancelError(
            "not_cancellable", f"This request is {status.lower()}.", 409
        )

    # An admin must justify the change; the employee may explain if they want.
    if actor_is_admin:
        if reason is None or len(reason) < 3:
            raise CancelError(
                "comment_required",
                "An administrator must give a reason of 3..1000 characters.",
                400,
            )
    if reason is not None and len(reason) > 1000:
        raise CancelError(
            "comment_too_long", "The comment must be at most 1000 characters.", 400
        )

    # Only a PENDING request still has approvals waiting for a decision.
    skipped = (
        [
            approver_id
            for approver_id, row_status in approvals
            if _text(row_status) == PENDING
        ]
        if status == PENDING
        else []
    )
    return CancelDecision(
        skipped_approver_ids=skipped,
        balance_effect=(
            BalanceEffect.RESTORE_USED if status == APPROVED else BalanceEffect.RELEASE
        ),
        comment=reason,
    )


def can_cancel(
    request_status,
    requester_id: int,
    actor_id: int,
    actor_is_admin: bool,
    *,
    touches_closed_year: bool = False,
) -> bool:
    """The same rule expressed as a yes/no, for the UI's `can_cancel` flag.

    A closed leave year always answers false, so the button can never appear
    where the API would refuse with 409.
    """
    if touches_closed_year:
        return False
    status = _text(request_status)
    is_requester = actor_id == requester_id
    if status == PENDING:
        return is_requester or actor_is_admin
    if status == APPROVED:
        return actor_is_admin
    return False
