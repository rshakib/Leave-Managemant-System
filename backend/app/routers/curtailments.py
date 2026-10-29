import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.models.leave_curtailment import (
    CurtailmentCreate,
    CurtailmentDecision,
    CurtailmentPreview,
    CurtailmentRead,
    CurtailmentStatus,
)
from app.services.curtailments import (
    approve_curtailment,
    cancel_curtailment,
    get_curtailment_preview,
    list_curtailments_for_request,
    list_inbox_curtailments,
    list_my_curtailments,
    reject_curtailment,
    submit_curtailment,
)

router = APIRouter(tags=["curtailments"])


@router.get(
    "/leave-requests/{request_id}/curtail/preview",
    response_model=CurtailmentPreview,
)
async def preview_curtailment(
    request_id: int,
    curtailed_end_date: datetime.date = Query(..., description="Proposed new earlier end date"),
    curtailed_day_type: Optional[str] = Query(default="FULL_DAY", description="Target day type: FULL_DAY, FIRST_HALF, SECOND_HALF"),
    current: Employee = Depends(require_roles(Role.EMPLOYEE)),
    session: AsyncSession = Depends(get_session),
) -> CurtailmentPreview:
    """Preview days and refund for an early return."""
    return await get_curtailment_preview(
        session, current, request_id, curtailed_end_date, curtailed_day_type
    )


@router.post(
    "/leave-requests/{request_id}/curtail",
    response_model=CurtailmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_curtailment(
    request_id: int,
    payload: CurtailmentCreate,
    current: Employee = Depends(require_roles(Role.EMPLOYEE)),
    session: AsyncSession = Depends(get_session),
) -> CurtailmentRead:
    """Submit an early return / curtailment request."""
    curtailment = await submit_curtailment(session, current, request_id, payload)
    rows = await list_curtailments_for_request(session, current, request_id)
    return next(r for r in rows if r.id == curtailment.id)


@router.get(
    "/leave-requests/{request_id}/curtailments",
    response_model=list[CurtailmentRead],
)
async def get_request_curtailments(
    request_id: int,
    current: Employee = Depends(require_roles(Role.EMPLOYEE)),
    session: AsyncSession = Depends(get_session),
) -> list[CurtailmentRead]:
    """List early return history for a leave request."""
    return await list_curtailments_for_request(session, current, request_id)


@router.get("/curtailments/inbox", response_model=list[CurtailmentRead])
async def get_inbox_curtailments(
    status_filter: CurtailmentStatus = Query(default=CurtailmentStatus.PENDING, alias="status"),
    current: Employee = Depends(require_roles(Role.APPROVER)),
    session: AsyncSession = Depends(get_session),
) -> list[CurtailmentRead]:
    """List early return requests waiting for approval by current approver."""
    return await list_inbox_curtailments(session, current, status_filter)


@router.get("/curtailments/my", response_model=list[CurtailmentRead])
async def get_my_curtailments(
    current: Employee = Depends(require_roles(Role.EMPLOYEE)),
    session: AsyncSession = Depends(get_session),
) -> list[CurtailmentRead]:
    """List caller's own early return requests."""
    return await list_my_curtailments(session, current)


@router.post(
    "/curtailments/{curtailment_id}/approve",
    response_model=CurtailmentRead,
)
async def approve_curtailment_endpoint(
    curtailment_id: int,
    payload: Optional[CurtailmentDecision] = None,
    current: Employee = Depends(require_roles(Role.APPROVER)),
    session: AsyncSession = Depends(get_session),
) -> CurtailmentRead:
    """Approve an early return request: refund unused days and update request end date."""
    note = payload.note if payload else None
    curtailment = await approve_curtailment(session, current, curtailment_id, note)
    rows = await list_curtailments_for_request(session, current, curtailment.leave_request_id)
    return next(r for r in rows if r.id == curtailment.id)


@router.post(
    "/curtailments/{curtailment_id}/reject",
    response_model=CurtailmentRead,
)
async def reject_curtailment_endpoint(
    curtailment_id: int,
    payload: CurtailmentDecision,
    current: Employee = Depends(require_roles(Role.APPROVER)),
    session: AsyncSession = Depends(get_session),
) -> CurtailmentRead:
    """Reject an early return request."""
    note = payload.note or ""
    curtailment = await reject_curtailment(session, current, curtailment_id, note)
    rows = await list_curtailments_for_request(session, current, curtailment.leave_request_id)
    return next(r for r in rows if r.id == curtailment.id)


@router.delete(
    "/curtailments/{curtailment_id}",
    response_model=CurtailmentRead,
)
async def cancel_curtailment_endpoint(
    curtailment_id: int,
    current: Employee = Depends(require_roles(Role.EMPLOYEE)),
    session: AsyncSession = Depends(get_session),
) -> CurtailmentRead:
    """Cancel a pending early return request."""
    curtailment = await cancel_curtailment(session, current, curtailment_id)
    rows = await list_curtailments_for_request(session, current, curtailment.leave_request_id)
    return next(r for r in rows if r.id == curtailment.id)

