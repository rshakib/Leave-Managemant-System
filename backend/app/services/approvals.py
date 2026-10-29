"""Approval actions (FR-LR-4) and a reconciliation check.

LOCK ORDER — always the same, everywhere:
    1. the `leave_request` row (SELECT ... FOR UPDATE), then
    2. that request's `leave_balance` rows, ordered by leave_year_id.
`submit()` in services/leave_requests.py uses the same order (employee row, then
balances by year). Taking locks in one global order means two transactions can
never each hold what the other needs, which is exactly what a deadlock is. Every
approver of the SAME request also serialises on the request lock, so two
simultaneous decisions cannot both "win".
"""

import datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.balance_adjustment import AdjustmentField, LeaveBalanceAdjustment
from app.models.leave_balance import LeaveBalance
from app.models.leave_request import (
    ApprovalStatus,
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
from app.services.approval_rules import (
    SKIPPED,
    Action,
    ApprovalError,
    BalanceEffect,
    decide,
)


async def act(
    session: AsyncSession,
    request_id: int,
    actor: Employee,
    action: Action,
    comment: str | None,
) -> LeaveRequest:
    """Approve or reject one request, in a single transaction."""
    # Step 1: does this actor even have a row? (404 == "request not found")
    approval = await session.scalar(
        select(LeaveRequestApproval).where(
            LeaveRequestApproval.leave_request_id == request_id,
            LeaveRequestApproval.approver_id == actor.id,
        )
    )
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    # Step 2: lock the request row, then re-read it and all approvals.
    request = await session.scalar(
        select(LeaveRequest)
        .where(LeaveRequest.id == request_id)
        .with_for_update()
        # populate_existing: SQLAlchemy would otherwise hand back the stale copy
        # already in the session's identity map (loaded before we took the lock),
        # and a double-click would be applied twice.
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

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
        decision = decide(
            request.status,
            request.employee_id,
            [(row.approver_id, row.status) for row in approvals],
            actor.id,
            action,
        )
    except ApprovalError as exc:
        await session.rollback()
        raise HTTPException(exc.http_status, exc.message) from None

    # Step 4: move or release the reserved days, using the allocation rows.
    # `balances` stays empty when this decision changes no balance (an
    # intermediate approval), so the audit snapshot below always has something.
    balances: dict = {}
    if decision.balance_effect is not BalanceEffect.NONE:
        allocations = (
            await session.scalars(
                select(LeaveRequestAllocation)
                .where(LeaveRequestAllocation.leave_request_id == request_id)
                .order_by(LeaveRequestAllocation.leave_year_id)
            )
        ).all()
        balances = {
            balance.leave_year_id: balance
            for balance in (
                await session.scalars(
                    select(LeaveBalance)
                    .where(
                        LeaveBalance.employee_id == request.employee_id,
                        LeaveBalance.leave_type_id == request.leave_type_id,
                        LeaveBalance.leave_year_id.in_(
                            [row.leave_year_id for row in allocations]
                        ),
                    )
                    .order_by(LeaveBalance.leave_year_id)
                    .with_for_update()
                )
            ).all()
        }

        for allocation in allocations:
            balance = balances.get(allocation.leave_year_id)
            if balance is None or Decimal(balance.pending) < Decimal(allocation.days):
                await session.rollback()
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "The reserved balance for this request is inconsistent "
                    f"(leave year id {allocation.leave_year_id}). Nothing was "
                    "changed; please contact an administrator.",
                )
            balance.pending = Decimal(balance.pending) - Decimal(allocation.days)
            if decision.balance_effect is BalanceEffect.MOVE_TO_USED:
                balance.used = Decimal(balance.used) + Decimal(allocation.days)

    before_balances = balance_snapshot(balances)

    # Step 5: write the statuses.
    now = datetime.datetime.now(datetime.timezone.utc)
    actor_row = None
    for row in approvals:
        if row.approver_id == actor.id:
            row.status = decision.actor_approval_status
            row.comment = comment
            row.acted_at = now
            actor_row = row
        elif row.approver_id in decision.skipped_approver_ids:
            row.status = SKIPPED
            row.acted_at = now

    request.status = decision.request_status
    if decision.request_status != RequestStatus.PENDING:
        request.final_decided_at = now

    # Queue the notification INSIDE this transaction (D-19).
    await session.flush()
    if decision.request_status == RequestStatus.APPROVED:
        event = "APPROVED"
    elif decision.request_status == RequestStatus.REJECTED:
        event = "REJECTED"
    else:
        event = "APPROVER_ACTED"
    await enqueue_events(
        session,
        event,
        await build_facts(
            session,
            request,
            balances=await _balances_after(session, request),
            extra={
                "actor_email": actor.email,
                "actor_name": actor.full_name,
                "approval_id": actor_row.id if actor_row is not None else None,
                "comment": comment,
            },
        ),
    )

    if decision.request_status != RequestStatus.PENDING:
        action = (
            "APPROVE"
            if decision.request_status == RequestStatus.APPROVED
            else "REJECT"
        )
    else:
        action = "APPROVE"
    await record(
        session,
        actor.id,
        "leave_request",
        request.id,
        action,
        old={"status": "PENDING",
             "balances": before_balances},
        new={"status": decision.request_status,
             "balances": balance_snapshot(balances)},
        reason=comment,
    )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The request changed while you were deciding. Please reload.",
        ) from None


    await session.refresh(request)
    return request


async def reconcile_balances(
    session: AsyncSession, employee_id: int
) -> list[dict]:
    """READ-ONLY invariant check: balances must match the requests.

    expected pending = sum of allocation days of this employee's PENDING requests
    expected used    = sum of allocation days of this employee's APPROVED requests
    Returns a list of mismatches; an empty list means everything is consistent.
    """
    rows = (
        await session.execute(
            select(
                LeaveRequest.leave_type_id,
                LeaveRequestAllocation.leave_year_id,
                LeaveRequest.status,
                LeaveRequestAllocation.days,
            )
            .join(
                LeaveRequest,
                LeaveRequest.id == LeaveRequestAllocation.leave_request_id,
            )
            .where(LeaveRequest.employee_id == employee_id)
        )
    ).all()

    expected: dict[tuple[int, int], dict[str, Decimal]] = {}
    for leave_type_id, leave_year_id, request_status, days in rows:
        key = (leave_type_id, leave_year_id)
        bucket = expected.setdefault(
            key, {"pending": Decimal("0"), "used": Decimal("0")}
        )
        if request_status == RequestStatus.PENDING:
            bucket["pending"] += Decimal(days)
        elif request_status == RequestStatus.APPROVED:
            bucket["used"] += Decimal(days)

    # Manual USED adjustments are part of the truth as well (D-156).
    for leave_type_id, leave_year_id, days in (
        await session.execute(
            select(
                LeaveBalanceAdjustment.leave_type_id,
                LeaveBalanceAdjustment.leave_year_id,
                func.coalesce(func.sum(LeaveBalanceAdjustment.delta), 0),
            )
            .where(
                LeaveBalanceAdjustment.employee_id == employee_id,
                LeaveBalanceAdjustment.field == AdjustmentField.USED.value,
            )
            .group_by(
                LeaveBalanceAdjustment.leave_type_id,
                LeaveBalanceAdjustment.leave_year_id,
            )
        )
    ).all():
        bucket = expected.setdefault(
            (leave_type_id, leave_year_id),
            {"pending": Decimal("0"), "used": Decimal("0")},
        )
        bucket["used"] += Decimal(days)

    balances = (
        await session.scalars(
            select(LeaveBalance).where(LeaveBalance.employee_id == employee_id)
        )
    ).all()

    mismatches: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for balance in balances:
        key = (balance.leave_type_id, balance.leave_year_id)
        seen.add(key)
        want = expected.get(key, {"pending": Decimal("0"), "used": Decimal("0")})
        if (
            Decimal(balance.pending) != want["pending"]
            or Decimal(balance.used) != want["used"]
        ):
            mismatches.append(
                {
                    "leave_type_id": key[0],
                    "leave_year_id": key[1],
                    "expected_pending": str(want["pending"]),
                    "actual_pending": str(balance.pending),
                    "expected_used": str(want["used"]),
                    "actual_used": str(balance.used),
                }
            )

    for key, want in expected.items():
        if key not in seen and (want["pending"] or want["used"]):
            mismatches.append(
                {
                    "leave_type_id": key[0],
                    "leave_year_id": key[1],
                    "expected_pending": str(want["pending"]),
                    "actual_pending": "(no balance row)",
                    "expected_used": str(want["used"]),
                    "actual_used": "(no balance row)",
                }
            )

    return mismatches


async def pending_request_count(session: AsyncSession, employee_id: int) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(LeaveRequest)
        .where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == RequestStatus.PENDING,
        )
    )
    return count or 0


async def pending_approval_count(session: AsyncSession, approver_id: int) -> int:
    """How many PENDING decisions this person still owes."""
    count = await session.scalar(
        select(func.count())
        .select_from(LeaveRequestApproval)
        .join(LeaveRequest, LeaveRequest.id == LeaveRequestApproval.leave_request_id)
        .where(
            LeaveRequestApproval.approver_id == approver_id,
            LeaveRequestApproval.status == ApprovalStatus.PENDING,
            LeaveRequest.status == RequestStatus.PENDING,
        )
    )
    return count or 0
