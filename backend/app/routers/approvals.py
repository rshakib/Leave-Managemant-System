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
    return InboxCount(pending=await pending_approval_count(session, current.id))


@router.get("/approvals/inbox", response_model=list[InboxItem])
async def inbox(
    status_filter: InboxFilter = Query(default=InboxFilter.PENDING, alias="status"),
    limit: int = 50,
    offset: int = 0,
    current: Employee = Depends(require_roles(Role.APPROVER)),
    session: AsyncSession = Depends(get_session),
) -> list[InboxItem]:
    """Only the caller's own approval rows — there is no user id parameter.

    Four queries in total (approvals+requests, employees, leave types, the
    other-approver counts) regardless of how many rows come back.
    """
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

    # Query 2: the employees who asked.
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
    # Query 3: the leave types.
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
    # Query 4: every approval on those requests, for the "n of m" summary.
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
