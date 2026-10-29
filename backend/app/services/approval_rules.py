"""The "all must approve" decision rules, as a PURE function (FR-APR-3).

No database, no HTTP, no clock — so the same rules can be unit-tested directly
and reused by the service.
"""

from dataclasses import dataclass, field
from enum import Enum

PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
CANCELLED = "CANCELLED"
SKIPPED = "SKIPPED"


class Action(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class BalanceEffect(str, Enum):
    NONE = "NONE"
    MOVE_TO_USED = "MOVE_TO_USED"
    RELEASE = "RELEASE"


class ApprovalError(Exception):
    """A rule was broken; `http_status` says how the API should answer."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


@dataclass(frozen=True)
class Decision:
    actor_approval_status: str
    skipped_approver_ids: list[int] = field(default_factory=list)
    request_status: str = PENDING
    balance_effect: BalanceEffect = BalanceEffect.NONE


def _text(value) -> str:
    """Accept plain strings or the model enums."""
    return value.value if hasattr(value, "value") else str(value)


def decide(
    request_status,
    request_employee_id: int,
    approvals: list[tuple[int, object]],
    actor_id: int,
    action,
) -> Decision:
    """Work out what one approve/reject does to the whole request.

    `approvals` is a list of `(approver_id, status)` pairs.
    """
    status = _text(request_status)
    chosen = Action(_text(action))
    rows = [(approver_id, _text(row_status)) for approver_id, row_status in approvals]

    # The requester can never decide their own request. This returns 403 (not a
    # hidden 404): the requester already knows their request exists.
    if actor_id == request_employee_id:
        raise ApprovalError(
            "own_request",
            "You cannot approve or reject your own leave request.",
            403,
        )

    # No row for this actor -> the same 404 as a missing request, so the
    # existence of a request is never leaked to a stranger.
    actor_status = next((row for approver_id, row in rows if approver_id == actor_id), None)
    if actor_status is None:
        raise ApprovalError("not_found", "Leave request not found.", 404)

    if status != PENDING:
        raise ApprovalError(
            "not_pending",
            f"This request is already {status.lower()}.",
            409,
        )

    if actor_status != PENDING:
        if actor_status == SKIPPED:
            raise ApprovalError(
                "skipped",
                "Your approval was skipped because another approver rejected "
                "the request.",
                409,
            )
        raise ApprovalError(
            "already_acted",
            f"You already {actor_status.lower()} this request.",
            409,
        )

    if chosen is Action.APPROVE:
        # Approved only when nobody else is still PENDING.
        still_pending = any(
            row == PENDING for approver_id, row in rows if approver_id != actor_id
        )
        if still_pending:
            return Decision(
                actor_approval_status=APPROVED,
                skipped_approver_ids=[],
                request_status=PENDING,
                balance_effect=BalanceEffect.NONE,
            )
        return Decision(
            actor_approval_status=APPROVED,
            skipped_approver_ids=[],
            request_status=APPROVED,
            balance_effect=BalanceEffect.MOVE_TO_USED,
        )

    # REJECT: close every other PENDING approval. Approvals that were already
    # APPROVED keep their status (history stays truthful).
    skipped = [
        approver_id
        for approver_id, row in rows
        if approver_id != actor_id and row == PENDING
    ]
    return Decision(
        actor_approval_status=REJECTED,
        skipped_approver_ids=skipped,
        request_status=REJECTED,
        balance_effect=BalanceEffect.RELEASE,
    )
