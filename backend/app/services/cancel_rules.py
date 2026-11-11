"""Pure rules for leave request cancellation."""

from dataclasses import dataclass, field
from datetime import date
from enum import Enum

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
SKIPPED = "SKIPPED"


class BalanceEffect(str, Enum):
    NONE = "NONE"
    RELEASE = "RELEASE"
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
    *,
    start_date: date | None = None,
    today: date | None = None,
) -> CancelDecision:
    status = _text(request_status)
    reason = (comment or "").strip() or None
    is_requester = actor_id == requester_id

    if not actor_can_see_request:
        raise CancelError("not_found", "Leave request not found.", 404)

    if status in (REJECTED, CANCELLED):
        raise CancelError(
            "not_cancellable", f"This request is already {status.lower()}.", 409
        )

    if start_date is not None and today is not None:
        if today >= start_date:
            raise CancelError(
                "leave_already_started",
                "Cannot cancel a leave request that has already started or passed.",
                400,
            )

    if status in (PENDING, APPROVED):
        if not (is_requester or actor_is_admin):
            raise CancelError(
                "forbidden",
                "Only the employee who requested this leave, or an administrator, can cancel it.",
                403,
            )
    else:
        raise CancelError(
            "not_cancellable", f"This request is {status.lower()}.", 409
        )

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
    start_date: date | None = None,
    today: date | None = None,
    touches_closed_year: bool = False,
) -> bool:
    """Return whether the actor can currently cancel the leave request."""
    if touches_closed_year:
        return False
    if start_date is not None and today is not None:
        if today >= start_date:
            return False
    status = _text(request_status)
    is_requester = actor_id == requester_id
    if status in (PENDING, APPROVED):
        return is_requester or actor_is_admin
    return False
