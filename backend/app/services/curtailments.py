"""Early return / leave curtailment service."""

import datetime
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import load_roles
from app.models.employee import Employee, Role
from app.models.employee_approver import EmployeeApprover
from app.models.leave_balance import LeaveBalance
from app.models.leave_curtailment import (
    CurtailmentCreate,
    CurtailmentPreview,
    CurtailmentRead,
    CurtailmentStatus,
    LeaveCurtailment,
)
from app.models.leave_request import (
    LeaveRequest,
    LeaveRequestAllocation,
    LeaveRequestApproval,
    RequestStatus,
)
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear
from app.services.audit import balance_snapshot, record
from app.services.calendar import build_preview
from app.services.curtailment_rules import (
    CurtailmentRuleError,
    calculate_curtailment_refund,
    can_request_curtailment,
    validate_curtailment_dates,
)
from app.services.day_calc import DayCalcError
from app.services.leave_requests import active_approvers
from app.services.notifications import balances_after, enqueue_events
from app.services.request_rules import split_days_by_leave_year


async def _get_approvers_for_curtailment(
    session: AsyncSession, request: LeaveRequest
) -> list[dict]:
    approvers = await active_approvers(session, request.employee_id)
    if not approvers:
        assigned_ids = (
            await session.scalars(
                select(LeaveRequestApproval.approver_id).where(
                    LeaveRequestApproval.leave_request_id == request.id
                )
            )
        ).all()
        if assigned_ids:
            approvers = list(
                (
                    await session.scalars(
                        select(Employee).where(
                            Employee.id.in_(assigned_ids),
                            Employee.is_active.is_(True),
                        )
                    )
                ).all()
            )
    return [
        {
            "id": a.id,
            "name": a.full_name,
            "email": a.email,
            "is_active": a.is_active,
        }
        for a in approvers
    ]


async def _check_curtailment_eligibility(
    session: AsyncSession, request: LeaveRequest
) -> tuple[bool, Optional[str]]:
    allocations = (
        await session.scalars(
            select(LeaveRequestAllocation).where(
                LeaveRequestAllocation.leave_request_id == request.id
            )
        )
    ).all()
    year_ids = [a.leave_year_id for a in allocations] or [request.leave_year_id]
    closed_count = (
        await session.scalar(
            select(LeaveYear.id).where(
                LeaveYear.id.in_(year_ids), LeaveYear.is_closed.is_(True)
            )
        )
    )
    touches_closed_year = closed_count is not None

    pending_curtailment = await session.scalar(
        select(LeaveCurtailment.id).where(
            LeaveCurtailment.leave_request_id == request.id,
            LeaveCurtailment.status == CurtailmentStatus.PENDING,
        )
    )
    has_pending = pending_curtailment is not None

    is_curtailable = (
        request.start_date < request.end_date
        or (
            request.start_date == request.end_date
            and request.day_type == "FULL_DAY"
            and request.chargeable_days > Decimal("0.5")
        )
    )

    import zoneinfo
    from app.core.config import settings

    today = datetime.datetime.now(zoneinfo.ZoneInfo(settings.org_timezone)).date()

    return can_request_curtailment(
        request_status=request.status,
        touches_closed_year=touches_closed_year,
        has_pending_curtailment=has_pending,
        is_curtailable=is_curtailable,
        start_date=request.start_date,
        end_date=request.end_date,
        today=today,
    )


async def get_curtailment_preview(
    session: AsyncSession,
    actor: Employee,
    request_id: int,
    curtailed_end_date: datetime.date,
    curtailed_day_type: Optional[str] = "FULL_DAY",
) -> CurtailmentPreview:
    request = await session.get(LeaveRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    roles = set(await load_roles(session, actor.id))
    if request.employee_id != actor.id and Role.ADMIN not in roles:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    employee = await session.get(Employee, request.employee_id)
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found.")

    can_curtail, err = await _check_curtailment_eligibility(session, request)
    if not can_curtail:
        return CurtailmentPreview(
            leave_request_id=request.id,
            original_end_date=request.end_date,
            curtailed_end_date=curtailed_end_date,
            curtailed_day_type=curtailed_day_type,
            original_days=request.chargeable_days,
            new_days=request.chargeable_days,
            days_to_refund=Decimal("0"),
            can_curtail=False,
            error=err,
        )

    target_day_type = (
        curtailed_day_type
        if curtailed_day_type in ("FULL_DAY", "FIRST_HALF", "SECOND_HALF")
        else request.day_type
    )

    try:
        validate_curtailment_dates(
            request.start_date,
            request.end_date,
            curtailed_end_date,
            str(request.day_type),
            str(target_day_type),
        )
    except CurtailmentRuleError as exc:
        return CurtailmentPreview(
            leave_request_id=request.id,
            original_end_date=request.end_date,
            curtailed_end_date=curtailed_end_date,
            curtailed_day_type=curtailed_day_type,
            original_days=request.chargeable_days,
            new_days=request.chargeable_days,
            days_to_refund=Decimal("0"),
            can_curtail=False,
            error=exc.message,
        )

    try:
        preview = await build_preview(
            session, employee, request.start_date, curtailed_end_date, target_day_type
        )
    except DayCalcError as exc:
        return CurtailmentPreview(
            leave_request_id=request.id,
            original_end_date=request.end_date,
            curtailed_end_date=curtailed_end_date,
            curtailed_day_type=curtailed_day_type,
            original_days=request.chargeable_days,
            new_days=request.chargeable_days,
            days_to_refund=Decimal("0"),
            can_curtail=False,
            error=str(exc),
        )

    new_days = preview.chargeable_days
    try:
        refund = calculate_curtailment_refund(request.chargeable_days, new_days)
    except CurtailmentRuleError as exc:
        return CurtailmentPreview(
            leave_request_id=request.id,
            original_end_date=request.end_date,
            curtailed_end_date=curtailed_end_date,
            curtailed_day_type=curtailed_day_type,
            original_days=request.chargeable_days,
            new_days=new_days,
            days_to_refund=Decimal("0"),
            can_curtail=False,
            error=exc.message,
        )

    return CurtailmentPreview(
        leave_request_id=request.id,
        original_end_date=request.end_date,
        curtailed_end_date=curtailed_end_date,
        curtailed_day_type=curtailed_day_type,
        original_days=request.chargeable_days,
        new_days=new_days,
        days_to_refund=refund,
        can_curtail=True,
        error=None,
    )


async def submit_curtailment(
    session: AsyncSession,
    actor: Employee,
    request_id: int,
    payload: CurtailmentCreate,
) -> LeaveCurtailment:
    reason = payload.reason.strip()
    if len(reason) < 3 or len(reason) > 1000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Early return reason must be between 3 and 1000 characters.",
        )

    request = await session.scalar(
        select(LeaveRequest)
        .where(LeaveRequest.id == request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    roles = set(await load_roles(session, actor.id))
    if request.employee_id != actor.id and Role.ADMIN not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to curtail this request.")

    can_curtail, err = await _check_curtailment_eligibility(session, request)
    if not can_curtail:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, err or "Cannot curtail request.")

    target_day_type = (
        payload.curtailed_day_type
        if payload.curtailed_day_type in ("FULL_DAY", "FIRST_HALF", "SECOND_HALF")
        else request.day_type
    )

    try:
        validate_curtailment_dates(
            request.start_date,
            request.end_date,
            payload.curtailed_end_date,
            str(request.day_type),
            str(target_day_type),
        )
    except CurtailmentRuleError as exc:
        raise HTTPException(exc.http_status, exc.message)

    employee = await session.get(Employee, request.employee_id)
    try:
        preview = await build_preview(
            session, employee, request.start_date, payload.curtailed_end_date, target_day_type
        )
    except DayCalcError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    new_days = preview.chargeable_days
    try:
        refund = calculate_curtailment_refund(request.chargeable_days, new_days)
    except CurtailmentRuleError as exc:
        raise HTTPException(exc.http_status, exc.message)

    curtailment = LeaveCurtailment(
        leave_request_id=request.id,
        employee_id=request.employee_id,
        original_end_date=request.end_date,
        curtailed_end_date=payload.curtailed_end_date,
        curtailed_day_type=str(target_day_type),
        original_days=request.chargeable_days,
        new_days=new_days,
        days_to_refund=refund,
        reason=reason,
        status=CurtailmentStatus.PENDING,
        submitted_at=datetime.datetime.now(datetime.timezone.utc),
    )
    session.add(curtailment)
    await session.flush()

    await record(
        session,
        actor.id,
        "leave_curtailment",
        curtailment.id,
        "SUBMIT",
        new={
            "leave_request_id": request.id,
            "curtailed_end_date": str(curtailment.curtailed_end_date),
            "original_days": str(curtailment.original_days),
            "new_days": str(curtailment.new_days),
            "days_to_refund": str(curtailment.days_to_refund),
            "reason": curtailment.reason,
            "status": curtailment.status,
        },
    )

    approver_list = await _get_approvers_for_curtailment(session, request)
    leave_type = await session.get(LeaveType, request.leave_type_id)
    curtailment_facts = {
        "curtailment_id": curtailment.id,
        "request_id": request.id,
        "employee_code": employee.employee_code if employee else "",
        "employee_name": employee.full_name if employee else "",
        "employee_email": employee.email if employee else "",
        "leave_type_code": leave_type.code if leave_type else "",
        "leave_type_name": leave_type.name if leave_type else "",
        "start_date": str(request.start_date),
        "original_end_date": str(curtailment.original_end_date),
        "end_date": str(curtailment.original_end_date),
        "curtailed_end_date": str(curtailment.curtailed_end_date),
        "curtailed_day_type": curtailment.curtailed_day_type,
        "original_days": str(curtailment.original_days),
        "new_days": str(curtailment.new_days),
        "chargeable_days": str(curtailment.new_days),
        "days_to_refund": str(curtailment.days_to_refund),
        "reason": curtailment.reason,
        "curtailment_reason": curtailment.reason,
        "approvers": approver_list,
    }
    await enqueue_events(session, "CURTAILMENT_SUBMITTED", curtailment_facts)

    await session.commit()
    await session.refresh(curtailment)
    return curtailment


async def _assert_approver_or_admin(
    session: AsyncSession, actor: Employee, request: LeaveRequest
) -> None:
    roles = set(await load_roles(session, actor.id))
    if Role.ADMIN in roles:
        return

    assigned = await session.scalar(
        select(LeaveRequestApproval.id).where(
            LeaveRequestApproval.leave_request_id == request.id,
            LeaveRequestApproval.approver_id == actor.id,
        )
    )
    if assigned is not None:
        return

    active_appr = await session.scalar(
        select(EmployeeApprover.id).where(
            EmployeeApprover.employee_id == request.employee_id,
            EmployeeApprover.approver_id == actor.id,
            EmployeeApprover.is_active.is_(True),
        )
    )
    if active_appr is not None:
        return

    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "You are not authorized to approve or reject this early return request.",
    )


async def approve_curtailment(
    session: AsyncSession,
    actor: Employee,
    curtailment_id: int,
    note: Optional[str] = None,
) -> LeaveCurtailment:
    """Approve an early return request and refund unused days to employee balances."""
    curtailment_peek = await session.get(LeaveCurtailment, curtailment_id)
    if curtailment_peek is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Early return request not found.")

    request = await session.scalar(
        select(LeaveRequest)
        .where(LeaveRequest.id == curtailment_peek.leave_request_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    await _assert_approver_or_admin(session, actor, request)

    curtailment = await session.scalar(
        select(LeaveCurtailment)
        .where(LeaveCurtailment.id == curtailment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if curtailment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Early return request not found.")

    if curtailment.status != CurtailmentStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This early return request is already {curtailment.status}.",
        )

    if request.status != RequestStatus.APPROVED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Associated leave request is no longer APPROVED (status is {request.status}).",
        )

    allocations = (
        await session.scalars(
            select(LeaveRequestAllocation)
            .where(LeaveRequestAllocation.leave_request_id == request.id)
            .order_by(LeaveRequestAllocation.leave_year_id)
        )
    ).all()
    year_ids = [a.leave_year_id for a in allocations] or [request.leave_year_id]

    employee = await session.get(Employee, request.employee_id)
    target_day_type = (
        curtailment.curtailed_day_type
        if curtailment.curtailed_day_type in ("FULL_DAY", "FIRST_HALF", "SECOND_HALF")
        else request.day_type
    )
    new_preview = await build_preview(
        session, employee, request.start_date, curtailment.curtailed_end_date, target_day_type
    )
    all_years = list((await session.scalars(select(LeaveYear))).all())
    new_splits = split_days_by_leave_year(new_preview.days, all_years, target_day_type)

    balances = {
        b.leave_year_id: b
        for b in (
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

    before_balances = balance_snapshot(balances)

    for alloc in allocations:
        old_alloc_days = Decimal(str(alloc.days))
        new_alloc_days = new_splits.get(alloc.leave_year_id, Decimal("0"))
        refund_for_year = old_alloc_days - new_alloc_days

        if refund_for_year > Decimal("0"):
            balance = balances.get(alloc.leave_year_id)
            if balance is not None:
                balance.used = max(Decimal("0"), Decimal(str(balance.used)) - refund_for_year)
            alloc.days = new_alloc_days

    request.end_date = curtailment.curtailed_end_date
    request.chargeable_days = curtailment.new_days
    if curtailment.curtailed_day_type:
        request.day_type = curtailment.curtailed_day_type

    now = datetime.datetime.now(datetime.timezone.utc)
    curtailment.status = CurtailmentStatus.APPROVED
    curtailment.decided_at = now
    curtailment.decided_by_id = actor.id
    curtailment.decision_note = note.strip() if note else None

    await record(
        session,
        actor.id,
        "leave_curtailment",
        curtailment.id,
        "APPROVE",
        new={
            "status": "APPROVED",
            "curtailed_end_date": str(curtailment.curtailed_end_date),
            "new_chargeable_days": str(request.chargeable_days),
            "days_refunded": str(curtailment.days_to_refund),
            "balances": balance_snapshot(balances),
        },
        old={"balances": before_balances},
    )

    employee = await session.get(Employee, request.employee_id)
    leave_type = await session.get(LeaveType, request.leave_type_id)
    approver_list = await _get_approvers_for_curtailment(session, request)
    curtailment_facts = {
        "curtailment_id": curtailment.id,
        "request_id": request.id,
        "employee_code": employee.employee_code if employee else "",
        "employee_name": employee.full_name if employee else "",
        "employee_email": employee.email if employee else "",
        "leave_type_code": leave_type.code if leave_type else "",
        "leave_type_name": leave_type.name if leave_type else "",
        "start_date": str(request.start_date),
        "original_end_date": str(curtailment.original_end_date),
        "curtailed_end_date": str(curtailment.curtailed_end_date),
        "curtailed_day_type": curtailment.curtailed_day_type,
        "original_days": str(curtailment.original_days),
        "new_days": str(curtailment.new_days),
        "chargeable_days": str(curtailment.new_days),
        "days_to_refund": str(curtailment.days_to_refund),
        "actor_name": actor.full_name,
        "actor_email": actor.email,
        "decision_note": curtailment.decision_note,
        "balances": await balances_after(session, request),
        "approvers": approver_list,
    }
    await enqueue_events(session, "CURTAILMENT_APPROVED", curtailment_facts)

    await session.commit()
    await session.refresh(curtailment)
    return curtailment


async def reject_curtailment(
    session: AsyncSession,
    actor: Employee,
    curtailment_id: int,
    note: str,
) -> LeaveCurtailment:
    note_clean = (note or "").strip()
    if len(note_clean) < 3 or len(note_clean) > 1000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Rejection note is required and must be between 3 and 1000 characters.",
        )

    curtailment = await session.scalar(
        select(LeaveCurtailment)
        .where(LeaveCurtailment.id == curtailment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if curtailment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Early return request not found.")

    if curtailment.status != CurtailmentStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This early return request is already {curtailment.status}.",
        )

    request = await session.get(LeaveRequest, curtailment.leave_request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    await _assert_approver_or_admin(session, actor, request)

    now = datetime.datetime.now(datetime.timezone.utc)
    curtailment.status = CurtailmentStatus.REJECTED
    curtailment.decided_at = now
    curtailment.decided_by_id = actor.id
    curtailment.decision_note = note_clean

    await record(
        session,
        actor.id,
        "leave_curtailment",
        curtailment.id,
        "REJECT",
        new={
            "status": "REJECTED",
            "decision_note": note_clean,
            "decided_by_id": actor.id,
        },
    )

    employee = await session.get(Employee, request.employee_id)
    leave_type = await session.get(LeaveType, request.leave_type_id)
    approver_list = await _get_approvers_for_curtailment(session, request)
    curtailment_facts = {
        "curtailment_id": curtailment.id,
        "request_id": request.id,
        "employee_code": employee.employee_code if employee else "",
        "employee_name": employee.full_name if employee else "",
        "employee_email": employee.email if employee else "",
        "leave_type_code": leave_type.code if leave_type else "",
        "leave_type_name": leave_type.name if leave_type else "",
        "start_date": str(request.start_date),
        "original_end_date": str(curtailment.original_end_date),
        "curtailed_end_date": str(curtailment.curtailed_end_date),
        "curtailed_day_type": curtailment.curtailed_day_type,
        "original_days": str(curtailment.original_days),
        "new_days": str(curtailment.new_days),
        "chargeable_days": str(curtailment.new_days),
        "days_to_refund": str(curtailment.days_to_refund),
        "actor_name": actor.full_name,
        "actor_email": actor.email,
        "decision_note": curtailment.decision_note,
        "approvers": approver_list,
    }
    await enqueue_events(session, "CURTAILMENT_REJECTED", curtailment_facts)

    await session.commit()
    await session.refresh(curtailment)
    return curtailment


async def cancel_curtailment(
    session: AsyncSession,
    actor: Employee,
    curtailment_id: int,
) -> LeaveCurtailment:
    curtailment = await session.scalar(
        select(LeaveCurtailment)
        .where(LeaveCurtailment.id == curtailment_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if curtailment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Early return request not found.")

    roles = set(await load_roles(session, actor.id))
    if curtailment.employee_id != actor.id and Role.ADMIN not in roles:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to cancel this early return request.")

    if curtailment.status != CurtailmentStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot cancel early return request in {curtailment.status} status.",
        )

    curtailment.status = CurtailmentStatus.CANCELLED
    await record(
        session,
        actor.id,
        "leave_curtailment",
        curtailment.id,
        "CANCEL",
        new={"status": "CANCELLED"},
    )

    await session.commit()
    await session.refresh(curtailment)
    return curtailment


async def list_curtailments_for_request(
    session: AsyncSession,
    actor: Employee,
    request_id: int,
) -> list[CurtailmentRead]:
    request = await session.get(LeaveRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    roles = set(await load_roles(session, actor.id))
    is_admin = Role.ADMIN in roles
    is_owner = request.employee_id == actor.id
    if not (is_admin or is_owner):
        is_approver = (
            await session.scalar(
                select(LeaveRequestApproval.id).where(
                    LeaveRequestApproval.leave_request_id == request_id,
                    LeaveRequestApproval.approver_id == actor.id,
                )
            )
        ) is not None
        if not is_approver:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    rows = (
        await session.scalars(
            select(LeaveCurtailment)
            .where(LeaveCurtailment.leave_request_id == request_id)
            .order_by(LeaveCurtailment.id.desc())
        )
    ).all()

    return await _to_read_models(session, rows)


async def list_inbox_curtailments(
    session: AsyncSession,
    actor: Employee,
    status_filter: CurtailmentStatus = CurtailmentStatus.PENDING,
) -> list[CurtailmentRead]:
    roles = set(await load_roles(session, actor.id))
    is_admin = Role.ADMIN in roles

    if is_admin:
        stmt = select(LeaveCurtailment).where(LeaveCurtailment.status == status_filter)
    else:
        subquery_appr = (
            select(EmployeeApprover.employee_id).where(
                EmployeeApprover.approver_id == actor.id,
                EmployeeApprover.is_active.is_(True),
            )
        )
        subquery_req = (
            select(LeaveRequestApproval.leave_request_id).where(
                LeaveRequestApproval.approver_id == actor.id,
            )
        )
        stmt = select(LeaveCurtailment).where(
            LeaveCurtailment.status == status_filter,
            or_(
                LeaveCurtailment.employee_id.in_(subquery_appr),
                LeaveCurtailment.leave_request_id.in_(subquery_req),
            ),
        )

    stmt = stmt.order_by(LeaveCurtailment.submitted_at.desc())
    rows = (await session.scalars(stmt)).all()
    return await _to_read_models(session, rows)


async def count_inbox_curtailments(
    session: AsyncSession,
    actor: Employee,
) -> int:
    roles = set(await load_roles(session, actor.id))
    is_admin = Role.ADMIN in roles

    if is_admin:
        stmt = (
            select(func.count())
            .select_from(LeaveCurtailment)
            .where(LeaveCurtailment.status == CurtailmentStatus.PENDING)
        )
    else:
        subquery_appr = (
            select(EmployeeApprover.employee_id).where(
                EmployeeApprover.approver_id == actor.id,
                EmployeeApprover.is_active.is_(True),
            )
        )
        subquery_req = (
            select(LeaveRequestApproval.leave_request_id).where(
                LeaveRequestApproval.approver_id == actor.id,
            )
        )
        stmt = (
            select(func.count())
            .select_from(LeaveCurtailment)
            .where(
                LeaveCurtailment.status == CurtailmentStatus.PENDING,
                or_(
                    LeaveCurtailment.employee_id.in_(subquery_appr),
                    LeaveCurtailment.leave_request_id.in_(subquery_req),
                ),
            )
        )
    return (await session.scalar(stmt)) or 0


async def list_my_curtailments(
    session: AsyncSession,
    actor: Employee,
) -> list[CurtailmentRead]:
    rows = (
        await session.scalars(
            select(LeaveCurtailment)
            .where(LeaveCurtailment.employee_id == actor.id)
            .order_by(LeaveCurtailment.submitted_at.desc())
        )
    ).all()
    return await _to_read_models(session, rows)


async def _to_read_models(
    session: AsyncSession, rows: list[LeaveCurtailment]
) -> list[CurtailmentRead]:
    if not rows:
        return []

    emp_ids = {r.employee_id for r in rows}
    decider_ids = {r.decided_by_id for r in rows if r.decided_by_id is not None}
    all_emp_ids = emp_ids | decider_ids
    employees = {
        e.id: e
        for e in (
            await session.scalars(
                select(Employee).where(Employee.id.in_(all_emp_ids))
            )
        ).all()
    }

    req_ids = {r.leave_request_id for r in rows}
    requests = {
        req.id: req
        for req in (
            await session.scalars(
                select(LeaveRequest).where(LeaveRequest.id.in_(req_ids))
            )
        ).all()
    }

    type_ids = {req.leave_type_id for req in requests.values()}
    leave_types = {
        t.id: t
        for t in (
            await session.scalars(
                select(LeaveType).where(LeaveType.id.in_(type_ids))
            )
        ).all()
    }

    out: list[CurtailmentRead] = []
    for r in rows:
        emp = employees.get(r.employee_id)
        decider = employees.get(r.decided_by_id) if r.decided_by_id else None
        req = requests.get(r.leave_request_id)
        lt = leave_types.get(req.leave_type_id) if req else None

        out.append(
            CurtailmentRead(
                id=r.id,
                leave_request_id=r.leave_request_id,
                employee_id=r.employee_id,
                employee_code=emp.employee_code if emp else None,
                employee_name=emp.full_name if emp else None,
                leave_type_name=lt.name if lt else None,
                original_start_date=req.start_date if req else None,
                original_end_date=r.original_end_date,
                curtailed_end_date=r.curtailed_end_date,
                curtailed_day_type=r.curtailed_day_type,
                original_days=r.original_days,
                new_days=r.new_days,
                days_to_refund=r.days_to_refund,
                reason=r.reason,
                status=r.status,
                submitted_at=r.submitted_at,
                decided_at=r.decided_at,
                decided_by_id=r.decided_by_id,
                decided_by_name=decider.full_name if decider else None,
                decision_note=r.decision_note,
            )
        )
    return out

