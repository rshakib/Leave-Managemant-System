"""Cancellation (FR-LR-5).

LOCK ORDER — deliberately identical to services/approvals.py:
    1. the `leave_request` row (SELECT ... FOR UPDATE), then
    2. that request's `leave_balance` rows, ordered by leave_year_id.
Every writer uses this same order, so two transactions can never each hold what
the other needs (a deadlock), and cancelling races with approving safely.

Why `.execution_options(populate_existing=True)`? Because SQLAlchemy keeps an
"identity map" of objects already loaded in the session. Without it, the re-read
after taking the lock would hand back the STALE copy loaded a moment earlier —
exactly the bug the Phase 11 concurrency test caught (a double-click being
applied twice).
"""

import datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import load_roles
from app.models.employee import Employee, Role
from app.models.leave_year import LeaveYear
from app.models.leave_balance import LeaveBalance
from app.models.leave_request import (
    LeaveRequest,
    LeaveRequestAllocation,
    LeaveRequestApproval,
    RequestStatus,
)
from app.services.audit import balance_snapshot, record
from app.services.notifications import (
    balances_after as _balances_after,
    build_facts,
    enqueue_events,
)
from app.services.cancel_rules import (
    SKIPPED,
    BalanceEffect,
    CancelError,
    closed_year_error,
    decide_cancel,
)

NOT_FOUND = "Leave request not found."


async def cancel(
    session: AsyncSession,
    request_id: int,
    actor: Employee,
    comment: str | None,
) -> LeaveRequest:
    """Cancel a PENDING (owner or admin) or an APPROVED (admin only) request.

    A PENDING cancellation releases `pending`; an APPROVED one restores `used`
    (D-194). A request touching a closed leave year is refused with 409.
    """
    # Step 1 (no lock yet): can this actor see the request at all?
    request = await session.get(LeaveRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)

    roles = set(await load_roles(session, actor.id))
    is_admin = Role.ADMIN in roles
    is_owner = request.employee_id == actor.id
    is_assigned = False
    if not (is_owner or is_admin):
        is_assigned = (
            await session.scalar(
                select(LeaveRequestApproval.id).where(
                    LeaveRequestApproval.leave_request_id == request_id,
                    LeaveRequestApproval.approver_id == actor.id,
                )
            )
        ) is not None
    actor_can_see = is_owner or is_admin or is_assigned

    # Step 2: lock the request row and re-read everything fresh.
    request = await session.scalar(
        select(LeaveRequest)
        .where(LeaveRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)

    approvals = (
        await session.scalars(
            select(LeaveRequestApproval)
            .where(LeaveRequestApproval.leave_request_id == request_id)
            .execution_options(populate_existing=True)
            .order_by(LeaveRequestApproval.approver_id)
        )
    ).all()

    # Step 3: the pure rules decide.
    try:
        decision = decide_cancel(
            request.status,
            request.employee_id,
            actor.id,
            is_admin,
            actor_can_see,
            [(row.approver_id, row.status) for row in approvals],
            comment,
        )
    except CancelError as exc:
        await session.rollback()
        raise HTTPException(exc.http_status, exc.message) from None

    # Step 4: undo the balance effect, using the allocation rows (not estimates).
    allocations = (
        await session.scalars(
            select(LeaveRequestAllocation)
            .where(LeaveRequestAllocation.leave_request_id == request_id)
            .order_by(LeaveRequestAllocation.leave_year_id)
        )
    ).all()

    # The dicts are initialised so the audit row below always has something to show.
    before_balances: dict = {}
    balances: dict = {}
    if decision.balance_effect is not BalanceEffect.NONE and allocations:
        year_ids = [row.leave_year_id for row in allocations]

        # A closed year's balance must never move: its days may already have been
        # carried forward (D-131/D-194). Take the SHARED year lock — the one the
        # year-end closing takes EXCLUSIVELY — and then re-check `is_closed`, so a
        # closing cannot slip in between this check and the balance change.
        years = (
            await session.scalars(
                select(LeaveYear)
                .where(LeaveYear.id.in_(year_ids))
                .order_by(LeaveYear.id)
                .with_for_update(read=True)
            )
        ).all()
        closed = [year.name for year in years if year.is_closed]
        if closed:
            await session.rollback()
            blocker = closed_year_error(closed)
            raise HTTPException(blocker.http_status, blocker.message)

        # Lock order stays: the request row (above), then the balance rows by
        # leave_year_id (D-96).
        balances = {
            balance.leave_year_id: balance
            for balance in (
                await session.scalars(
                    select(LeaveBalance)
                    .where(
                        LeaveBalance.employee_id == request.employee_id,
                        LeaveBalance.leave_type_id == request.leave_type_id,
                        LeaveBalance.leave_year_id.in_(year_ids),
                    )
                    .order_by(LeaveBalance.leave_year_id)
                    .with_for_update()
                )
            ).all()
        }

        # RELEASE gives the reserved days back; RESTORE_USED puts the charged days
        # back. Both simply move one field down by the allocation, and neither is
        # ever allowed to go below zero.
        field = (
            "pending"
            if decision.balance_effect is BalanceEffect.RELEASE
            else "used"
        )
        before_balances = balance_snapshot(balances)
        for allocation in allocations:
            days = Decimal(allocation.days)
            balance = balances.get(allocation.leave_year_id)
            if balance is None:
                await session.rollback()
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "The balance for this request is missing. Nothing was changed.",
                )
            current = Decimal(getattr(balance, field))
            if current < days:
                await session.rollback()
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"The {field} balance for this request is inconsistent. "
                    "Nothing was changed; please contact an administrator.",
                )
            setattr(balance, field, current - days)

    # Step 5: write the cancellation record. `final_decided_at` is NOT touched:
    # it records when the approval decision happened, which stays true.
    now = datetime.datetime.now(datetime.timezone.utc)
    for row in approvals:
        if row.approver_id in decision.skipped_approver_ids:
            row.status = SKIPPED
            row.acted_at = now

    status_before = request.status
    request.status = RequestStatus.CANCELLED
    request.cancelled_at = now
    request.cancelled_by_id = actor.id
    request.cancel_reason = decision.comment

    # Cancelling a PENDING request releases `pending`. Any refusal raises before
    # this point, so nothing is audited when nothing changed.
    await record(
        session,
        actor.id,
        "leave_request",
        request.id,
        "CANCEL",
        old={"status": str(status_before), "balances": before_balances},
        new={"status": "CANCELLED", "balances": balance_snapshot(balances)},
        reason=decision.comment,
    )

    # Queue the cancellation emails INSIDE this transaction (D-19): CANCELLED to
    # the approvers, plus CANCELLED_EMPLOYEE to the requester when an
    # administrator cancelled somebody else's request (D-115).
    await session.flush()
    await enqueue_events(
        session,
        "CANCELLED",
        await build_facts(
            session,
            request,
            balances=await _balances_after(session, request),
            extra={
                "cancelled_by_admin": is_admin and actor.id != request.employee_id,
                "previous_status": str(status_before),
                "cancelled_by_name": actor.full_name,
                "cancel_reason": decision.comment,
                "actor_email": actor.email,
            },
        ),
    )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The request changed while you were cancelling it. Please reload.",
        ) from None

    await session.refresh(request)
    return request
