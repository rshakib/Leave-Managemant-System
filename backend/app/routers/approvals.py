import datetime
from decimal import Decimal
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel

from app.core.deps import require_roles
from app.db.session import get_session
from app.models.auth_tokens import ApprovalActionToken
from app.models.employee import Employee, Role
from app.models.leave_request import (
    ApprovalStatus,
    DecisionResult,
    InboxCount,
    InboxItem,
    LeaveRequest,
    LeaveRequestApproval,
    RequestStatus,
)
from app.models.leave_type import LeaveType
from app.services.approval_rules import Action
from app.services.approvals import act, pending_approval_count
from app.services.curtailments import count_inbox_curtailments
from app.services.security_rules import hash_token

router = APIRouter(tags=["approvals"])

APPROVER = Depends(require_roles(Role.APPROVER))

MAX_REASON_PREVIEW = 80


class ApproveIn(SQLModel):
    comment: str | None = Field(default=None, max_length=1000)


class RejectIn(SQLModel):
    comment: str = Field(max_length=1000)


class InboxFilter(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"


def _preview(text: str) -> str:
    return text if len(text) <= MAX_REASON_PREVIEW else text[:MAX_REASON_PREVIEW] + "…"


@router.post(
    "/leave-requests/{request_id}/approve", response_model=DecisionResult
)
async def approve_request(
    request_id: int,
    payload: ApproveIn,
    current: Employee = Depends(require_roles(Role.APPROVER)),
    session: AsyncSession = Depends(get_session),
) -> DecisionResult:
    comment = (payload.comment or "").strip() or None
    request = await act(session, request_id, current, Action.APPROVE, comment)
    return DecisionResult(request_id=request.id, status=RequestStatus(request.status))


@router.post(
    "/leave-requests/{request_id}/reject", response_model=DecisionResult
)
async def reject_request(
    request_id: int,
    payload: RejectIn,
    current: Employee = Depends(require_roles(Role.APPROVER)),
    session: AsyncSession = Depends(get_session),
) -> DecisionResult:
    comment = payload.comment.strip()
    if not 3 <= len(comment) <= 1000:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The rejection reason must be 3..1000 characters.",
        )
    request = await act(session, request_id, current, Action.REJECT, comment)
    return DecisionResult(request_id=request.id, status=RequestStatus(request.status))


@router.get("/approvals/inbox/count", response_model=InboxCount)
async def inbox_count(
    current: Employee = Depends(require_roles(Role.APPROVER)),
    session: AsyncSession = Depends(get_session),
) -> InboxCount:
    pending_leaves = await pending_approval_count(session, current.id)
    pending_curtailments = await count_inbox_curtailments(session, current)
    return InboxCount(
        pending=pending_leaves,
        early_returns=pending_curtailments,
        total=pending_leaves + pending_curtailments,
    )


@router.get("/approvals/inbox", response_model=list[InboxItem])
async def inbox(
    status_filter: InboxFilter = Query(default=InboxFilter.PENDING, alias="status"),
    limit: int = 50,
    offset: int = 0,
    current: Employee = Depends(require_roles(Role.APPROVER)),
    session: AsyncSession = Depends(get_session),
) -> list[InboxItem]:
    statement = (
        select(LeaveRequestApproval, LeaveRequest)
        .join(LeaveRequest, LeaveRequest.id == LeaveRequestApproval.leave_request_id)
        .where(LeaveRequestApproval.approver_id == current.id)
    )
    if status_filter is InboxFilter.PENDING:
        statement = statement.where(
            LeaveRequestApproval.status == ApprovalStatus.PENDING,
            LeaveRequest.status == RequestStatus.PENDING,
        )
    else:
        statement = statement.where(
            LeaveRequestApproval.status != ApprovalStatus.PENDING
        )
    statement = (
        statement.order_by(
            LeaveRequest.submitted_at.desc(), LeaveRequest.id.desc()
        )
        .offset(max(0, offset))
        .limit(min(max(1, limit), 100))
    )
    rows = (await session.execute(statement)).all()
    if not rows:
        return []

    request_ids = {request.id for _, request in rows}

    employees = {
        employee.id: employee
        for employee in (
            await session.scalars(
                select(Employee).where(
                    Employee.id.in_({request.employee_id for _, request in rows})
                )
            )
        ).all()
    }
    leave_types = {
        leave_type.id: leave_type
        for leave_type in (
            await session.scalars(
                select(LeaveType).where(
                    LeaveType.id.in_({request.leave_type_id for _, request in rows})
                )
            )
        ).all()
    }
    all_approvals = (
        await session.execute(
            select(
                LeaveRequestApproval.leave_request_id,
                LeaveRequestApproval.status,
            ).where(LeaveRequestApproval.leave_request_id.in_(request_ids))
        )
    ).all()
    counts: dict[int, dict[str, int]] = {}
    for request_id, approval_status in all_approvals:
        bucket = counts.setdefault(request_id, {"total": 0, "approved": 0})
        bucket["total"] += 1
        if approval_status == ApprovalStatus.APPROVED:
            bucket["approved"] += 1

    items: list[InboxItem] = []
    for approval, request in rows:
        employee = employees[request.employee_id]
        leave_type = leave_types[request.leave_type_id]
        bucket = counts.get(request.id, {"total": 0, "approved": 0})
        items.append(
            InboxItem(
                approval_id=approval.id,
                approval_status=ApprovalStatus(approval.status),
                request_id=request.id,
                employee_id=employee.id,
                employee_code=employee.employee_code,
                employee_name=employee.full_name,
                leave_type_code=leave_type.code,
                leave_type_name=leave_type.name,
                start_date=request.start_date,
                end_date=request.end_date,
                day_type=request.day_type,
                chargeable_days=Decimal(request.chargeable_days),
                reason_preview=_preview(request.reason),
                submitted_at=request.submitted_at,
                approved_count=bucket["approved"],
                total_approvers=bucket["total"],
                summary=f"{bucket['approved']} of {bucket['total']} approved",
            )
        )
    return items


class QuickApprovalVerifyOut(SQLModel):
    request_id: int
    employee_name: str
    employee_code: str
    leave_type_name: str
    leave_type_code: str
    start_date: datetime.date
    end_date: datetime.date
    day_type: str
    chargeable_days: Decimal
    reason: str
    approver_name: str
    suggested_action: str
    request_status: str
    approval_status: str


class QuickApprovalDecideIn(SQLModel):
    token: str
    action: Action = Action.APPROVE
    comment: str | None = Field(default=None, max_length=1000)


class QuickApprovalDecideOut(SQLModel):
    ok: bool = True
    message: str
    request_id: int
    status: RequestStatus
    already_decided: bool = False
    employee_name: str | None = None
    leave_type_name: str | None = None
    start_date: datetime.date | None = None
    end_date: datetime.date | None = None
    chargeable_days: Decimal | None = None


@router.get("/approvals/quick-verify", response_model=QuickApprovalVerifyOut)
async def quick_verify(
    token: str,
    action: str = "APPROVE",
    session: AsyncSession = Depends(get_session),
) -> QuickApprovalVerifyOut:
    token_str = (token or "").strip()
    if not token_str:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Token is required.")
    token_hash = hash_token(token_str)
    token_record = await session.scalar(
        select(ApprovalActionToken).where(ApprovalActionToken.token_hash == token_hash)
    )
    if token_record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid approval token.")

    approval = await session.get(LeaveRequestApproval, token_record.approval_id)
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval record not found.")

    leave_req = await session.get(LeaveRequest, approval.leave_request_id)
    if leave_req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    if approval.status in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED) or (
        leave_req and leave_req.status in (RequestStatus.APPROVED, RequestStatus.REJECTED)
    ):
        employee = await session.get(Employee, leave_req.employee_id)
        approver = await session.get(Employee, approval.approver_id)
        leave_type = await session.get(LeaveType, leave_req.leave_type_id)
        return QuickApprovalVerifyOut(
            request_id=leave_req.id,
            employee_name=employee.full_name if employee else "",
            employee_code=employee.employee_code if employee else "",
            leave_type_name=leave_type.name if leave_type else "",
            leave_type_code=leave_type.code if leave_type else "",
            start_date=leave_req.start_date,
            end_date=leave_req.end_date,
            day_type=leave_req.day_type,
            chargeable_days=leave_req.chargeable_days,
            reason=leave_req.reason,
            approver_name=approver.full_name if approver else "",
            suggested_action=action.upper() if action in ("APPROVE", "REJECT") else "APPROVE",
            request_status=leave_req.status,
            approval_status=approval.status,
        )

    if token_record.used_at is not None:
        raise HTTPException(
            status.HTTP_410_GONE, "This approval link has already been used."
        )

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if token_record.expires_at < now_utc:
        raise HTTPException(
            status.HTTP_410_GONE, "This approval link has expired."
        )

    if approval.status != ApprovalStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You have already {approval.status.lower()} this request.",
        )

    if leave_req.status != RequestStatus.PENDING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"This leave request is already {leave_req.status.lower()}.",
        )

    employee = await session.get(Employee, leave_req.employee_id)
    approver = await session.get(Employee, approval.approver_id)
    leave_type = await session.get(LeaveType, leave_req.leave_type_id)

    suggested = action.upper() if action and action.upper() in ("APPROVE", "REJECT") else token_record.action

    return QuickApprovalVerifyOut(
        request_id=leave_req.id,
        employee_name=employee.full_name if employee else "",
        employee_code=employee.employee_code if employee else "",
        leave_type_name=leave_type.name if leave_type else "",
        leave_type_code=leave_type.code if leave_type else "",
        start_date=leave_req.start_date,
        end_date=leave_req.end_date,
        day_type=leave_req.day_type,
        chargeable_days=leave_req.chargeable_days,
        reason=leave_req.reason,
        approver_name=approver.full_name if approver else "",
        suggested_action=suggested,
        request_status=leave_req.status,
        approval_status=approval.status,
    )


@router.post("/approvals/quick-decide", response_model=QuickApprovalDecideOut)
async def quick_decide(
    payload: QuickApprovalDecideIn,
    session: AsyncSession = Depends(get_session),
) -> QuickApprovalDecideOut:
    token_str = (payload.token or "").strip()
    if not token_str:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Token is required.")
    token_hash = hash_token(token_str)
    token_record = await session.scalar(
        select(ApprovalActionToken).where(ApprovalActionToken.token_hash == token_hash)
    )
    if token_record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid approval token.")

    approval = await session.get(LeaveRequestApproval, token_record.approval_id)
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approval record not found.")

    leave_req = await session.get(LeaveRequest, approval.leave_request_id)

    if approval.status == ApprovalStatus.APPROVED or (leave_req and leave_req.status == RequestStatus.APPROVED):
        emp = await session.get(Employee, leave_req.employee_id) if leave_req else None
        lt = await session.get(LeaveType, leave_req.leave_type_id) if leave_req else None
        return QuickApprovalDecideOut(
            ok=True,
            message=f"Leave request for {emp.full_name if emp else 'employee'} has already been approved.",
            request_id=leave_req.id if leave_req else approval.leave_request_id,
            status=RequestStatus.APPROVED,
            already_decided=True,
            employee_name=emp.full_name if emp else None,
            leave_type_name=lt.name if lt else None,
            start_date=leave_req.start_date if leave_req else None,
            end_date=leave_req.end_date if leave_req else None,
            chargeable_days=leave_req.chargeable_days if leave_req else None,
        )

    if approval.status == ApprovalStatus.REJECTED or (leave_req and leave_req.status == RequestStatus.REJECTED):
        emp = await session.get(Employee, leave_req.employee_id) if leave_req else None
        lt = await session.get(LeaveType, leave_req.leave_type_id) if leave_req else None
        return QuickApprovalDecideOut(
            ok=True,
            message=f"Leave request for {emp.full_name if emp else 'employee'} has already been rejected.",
            request_id=leave_req.id if leave_req else approval.leave_request_id,
            status=RequestStatus.REJECTED,
            already_decided=True,
            employee_name=emp.full_name if emp else None,
            leave_type_name=lt.name if lt else None,
            start_date=leave_req.start_date if leave_req else None,
            end_date=leave_req.end_date if leave_req else None,
            chargeable_days=leave_req.chargeable_days if leave_req else None,
        )

    if token_record.used_at is not None:
        raise HTTPException(
            status.HTTP_410_GONE, "This approval link has already been used."
        )

    now_utc = datetime.datetime.now(datetime.timezone.utc)
    if token_record.expires_at < now_utc:
        raise HTTPException(
            status.HTTP_410_GONE, "This approval link has expired."
        )

    approver = await session.get(Employee, approval.approver_id)
    if approver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Approver not found.")

    comment = (payload.comment or "").strip() or None
    if payload.action == Action.REJECT:
        if not comment or len(comment) < 3:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "The rejection reason must be 3..1000 characters.",
            )

    try:
        leave_req = await act(
            session,
            approval.leave_request_id,
            approver,
            payload.action,
            comment or "Decided via email magic link",
        )
    except HTTPException as exc:
        if exc.status_code == 409 and "already approved" in str(exc.detail).lower():
            emp = await session.get(Employee, leave_req.employee_id) if leave_req else None
            lt = await session.get(LeaveType, leave_req.leave_type_id) if leave_req else None
            return QuickApprovalDecideOut(
                ok=True,
                message=f"Leave request for {emp.full_name if emp else 'employee'} has already been approved.",
                request_id=approval.leave_request_id,
                status=RequestStatus.APPROVED,
                already_decided=True,
                employee_name=emp.full_name if emp else None,
                leave_type_name=lt.name if lt else None,
                start_date=leave_req.start_date if leave_req else None,
                end_date=leave_req.end_date if leave_req else None,
                chargeable_days=leave_req.chargeable_days if leave_req else None,
            )
        if exc.status_code == 409 and "already rejected" in str(exc.detail).lower():
            emp = await session.get(Employee, leave_req.employee_id) if leave_req else None
            lt = await session.get(LeaveType, leave_req.leave_type_id) if leave_req else None
            return QuickApprovalDecideOut(
                ok=True,
                message=f"Leave request for {emp.full_name if emp else 'employee'} has already been rejected.",
                request_id=approval.leave_request_id,
                status=RequestStatus.REJECTED,
                already_decided=True,
                employee_name=emp.full_name if emp else None,
                leave_type_name=lt.name if lt else None,
                start_date=leave_req.start_date if leave_req else None,
                end_date=leave_req.end_date if leave_req else None,
                chargeable_days=leave_req.chargeable_days if leave_req else None,
            )
        raise

    token_record.used_at = now_utc
    session.add(token_record)
    await session.commit()

    emp = await session.get(Employee, leave_req.employee_id) if leave_req else None
    lt = await session.get(LeaveType, leave_req.leave_type_id) if leave_req else None
    action_word = "approved" if payload.action == Action.APPROVE else "declined"
    name_str = f" for {emp.full_name}" if emp else ""
    return QuickApprovalDecideOut(
        ok=True,
        message=f"Leave request{name_str} has been {action_word} successfully.",
        request_id=leave_req.id,
        status=RequestStatus(leave_req.status),
        already_decided=False,
        employee_name=emp.full_name if emp else None,
        leave_type_name=lt.name if lt else None,
        start_date=leave_req.start_date if leave_req else None,
        end_date=leave_req.end_date if leave_req else None,
        chargeable_days=leave_req.chargeable_days if leave_req else None,
    )
