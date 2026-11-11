"""Leave request cancellation service."""

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
    """Cancel a pending or approved leave request and update balances."""
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

    import zoneinfo
    from app.core.config import settings

    today = datetime.datetime.now(zoneinfo.ZoneInfo(settings.org_timezone)).date()
    try:
        decision = decide_cancel(
            request.status,
            request.employee_id,
            actor.id,
            is_admin,
            actor_can_see,
            [(row.approver_id, row.status) for row in approvals],
            comment,
            start_date=request.start_date,
            today=today,
        )
    except CancelError as exc:
        await session.rollback()
        raise HTTPException(exc.http_status, exc.message) from None

    allocations = (
        await session.scalars(
            select(LeaveRequestAllocation)
            .where(LeaveRequestAllocation.leave_request_id == request_id)
            .order_by(LeaveRequestAllocation.leave_year_id)
        )
    ).all()

    before_balances: dict = {}
    balances: dict = {}
    if decision.balance_effect is not BalanceEffect.NONE and allocations:
        year_ids = [row.leave_year_id for row in allocations]

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
