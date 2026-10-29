import datetime
from decimal import Decimal

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_user, load_roles, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.models.leave_request import (
    AdminRequestRow,
    AllocationRead,
    ApprovalRead,
    ApprovalStatus,
    CancelIn,
    DecisionResult,
    LeaveRequest,
    LeaveRequestAllocation,
    LeaveRequestApproval,
    LeaveRequestCheck,
    LeaveRequestDetail,
    LeaveRequestSummary,
    RequestStatus,
)
from app.models.leave_curtailment import CurtailmentStatus
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear
from app.services import storage
from app.services.cancel_rules import can_cancel
from app.services.cancellations import cancel as cancel_request
from app.services.curtailments import list_curtailments_for_request
from app.services.day_calc import DayType
from app.services.leave_requests import evaluate, submit

router = APIRouter(prefix="/leave-requests", tags=["leave-requests"])


MEDIA_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

MAX_REASON = 1000

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]


def _summary(request: LeaveRequest, leave_type: LeaveType) -> LeaveRequestSummary:
    return LeaveRequestSummary(
        id=request.id,
        leave_type_id=request.leave_type_id,
        leave_type_code=leave_type.code,
        leave_type_name=leave_type.name,
        leave_year_id=request.leave_year_id,
        start_date=request.start_date,
        end_date=request.end_date,
        day_type=DayType(request.day_type),
        chargeable_days=Decimal(request.chargeable_days),
        status=RequestStatus(request.status),
        submitted_at=request.submitted_at,
        has_attachment=bool(request.attachment_url),
    )


async def _detail(
    session: AsyncSession, request: LeaveRequest, current: Employee
) -> LeaveRequestDetail:
    leave_type = await session.get(LeaveType, request.leave_type_id)
    employee = await session.get(Employee, request.employee_id)

    allocations = (
        await session.scalars(
            select(LeaveRequestAllocation)
            .where(LeaveRequestAllocation.leave_request_id == request.id)
            .order_by(LeaveRequestAllocation.leave_year_id)
        )
    ).all()
    years = {}
    if allocations:
        years = {
            year.id: year
            for year in (
                await session.scalars(
                    select(LeaveYear).where(
                        LeaveYear.id.in_({row.leave_year_id for row in allocations})
                    )
                )
            ).all()
        }

    approvals = (
        await session.scalars(
            select(LeaveRequestApproval)
            .where(LeaveRequestApproval.leave_request_id == request.id)
            .order_by(LeaveRequestApproval.id)
        )
    ).all()
    people = {}
    if approvals:
        people = {
            person.id: person
            for person in (
                await session.scalars(
                    select(Employee).where(
                        Employee.id.in_({row.approver_id for row in approvals})
                    )
                )
            ).all()
        }

    mine = any(
        row.approver_id == current.id and row.status == ApprovalStatus.PENDING
        for row in approvals
    ) and request.status == RequestStatus.PENDING

    actor_roles = set(await load_roles(session, current.id))
    canceller = (
        await session.get(Employee, request.cancelled_by_id)
        if request.cancelled_by_id is not None
        else None
    )

    # Which of this request's leave years are already closed?
    touched_year_ids = {row.leave_year_id for row in allocations}
    closed_year_names = sorted(
        year.name
        for year in (
            await session.scalars(
                select(LeaveYear).where(LeaveYear.id.in_(touched_year_ids))
            )
        ).all()
        if year.is_closed
    ) if touched_year_ids else []

    curtailments = await list_curtailments_for_request(session, current, request.id)
    has_pending_curtailment = any(c.status == CurtailmentStatus.PENDING for c in curtailments)
    is_owner_or_admin = (request.employee_id == current.id) or (Role.ADMIN in actor_roles)
    is_curtailable = (
        request.start_date < request.end_date
        or (
            request.start_date == request.end_date
            and request.day_type == DayType.FULL_DAY
            and Decimal(str(request.chargeable_days)) > Decimal("0.5")
        )
    )
    can_curtail = (
        request.status == RequestStatus.APPROVED
        and is_owner_or_admin
        and not bool(closed_year_names)
        and not has_pending_curtailment
        and is_curtailable
    )

    return LeaveRequestDetail(
        **_summary(request, leave_type).model_dump(),
        touches_closed_year=bool(closed_year_names),
        closed_year_names=closed_year_names,
        my_pending_approval=mine,
        can_curtail=can_curtail,
        curtailments=curtailments,
        can_cancel=can_cancel(
            request.status,
            request.employee_id,
            current.id,
            Role.ADMIN in actor_roles,
            # A closed leave year can never be cancelled (D-194), so the flag the
            # UI reads already says so instead of letting the call fail with 409.
            touches_closed_year=bool(closed_year_names),
        ),
        cancelled_at=request.cancelled_at,
        cancelled_by_id=request.cancelled_by_id,
        cancelled_by_name=canceller.full_name if canceller else None,
        cancel_reason=request.cancel_reason,
        employee_id=employee.id,
        employee_code=employee.employee_code,
        employee_name=employee.full_name,
        reason=request.reason,
        final_decided_at=request.final_decided_at,
        allocations=[
            AllocationRead(
                leave_year_id=row.leave_year_id,
                leave_year_name=years[row.leave_year_id].name,
                days=Decimal(row.days),
            )
            for row in allocations
            if row.leave_year_id in years
        ],
        approvals=[
            ApprovalRead(
                approver_id=row.approver_id,
                approver_code=people[row.approver_id].employee_code,
                approver_name=people[row.approver_id].full_name,
                status=ApprovalStatus(row.status),
                comment=row.comment,
                acted_at=row.acted_at,
            )
            for row in approvals
            if row.approver_id in people
        ],
    )


async def _visible_or_404(
    session: AsyncSession, request_id: int, current: Employee
) -> LeaveRequest:
    """Owner, ADMIN, or an approver assigned to THIS request. Everyone else 404."""
    request = await session.get(LeaveRequest, request_id)
    if request is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")

    if request.employee_id == current.id:
        return request

    roles = set(await load_roles(session, current.id))
    if Role.ADMIN in roles:
        return request

    assigned = await session.scalar(
        select(LeaveRequestApproval.id).where(
            LeaveRequestApproval.leave_request_id == request_id,
            LeaveRequestApproval.approver_id == current.id,
        )
    )
    if assigned is None:
        # 404, not 403: do not reveal that this request exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found.")
    return request


# NOTE: fixed paths are declared before "/{request_id}" so they are matched first.


@router.get("/check", response_model=LeaveRequestCheck)
async def check_leave_request(
    leave_type_id: int,
    start_date: datetime.date,
    end_date: datetime.date,
    day_type: DayType = DayType.FULL_DAY,
    has_attachment: bool = False,
    current: Employee = Depends(require_roles(Role.EMPLOYEE)),
    session: AsyncSession = Depends(get_session),
) -> LeaveRequestCheck:
    """Read-only preview: the same rules the real submit will apply."""
    return await evaluate(
        session, current, leave_type_id, start_date, end_date, day_type, has_attachment
    )


@router.post(
    "", response_model=LeaveRequestSummary, status_code=status.HTTP_201_CREATED
)
async def create_leave_request(
    leave_type_id: int = Form(...),
    start_date: datetime.date = Form(...),
    end_date: datetime.date = Form(...),
    day_type: DayType = Form(DayType.FULL_DAY),
    reason: str = Form(...),
    attachment: UploadFile | None = File(None),
    current: Employee = Depends(require_roles(Role.EMPLOYEE)),
    session: AsyncSession = Depends(get_session),
) -> LeaveRequestSummary:
    cleaned_reason = reason.strip()
    if not 1 <= len(cleaned_reason) <= MAX_REASON:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"The reason must be 1..{MAX_REASON} characters.",
        )

    stored: str | None = None
    if attachment is not None and attachment.filename:
        stored = await storage.save(attachment)

    try:
        request = await submit(
            session,
            current,
            leave_type_id,
            start_date,
            end_date,
            day_type,
            cleaned_reason,
            stored,
        )
    except Exception:
        # The database part failed after the file was written: remove the file.
        if stored is not None:
            storage.delete(stored)
        raise

    leave_type = await session.get(LeaveType, request.leave_type_id)
    return _summary(request, leave_type)


@router.get("/me", response_model=list[LeaveRequestSummary])
async def my_leave_requests(
    status_filter: RequestStatus | None = Query(default=None, alias="status"),
    leave_year_id: int | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
    current: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[LeaveRequestSummary]:
    statement = select(LeaveRequest).where(LeaveRequest.employee_id == current.id)
    if status_filter is not None:
        statement = statement.where(LeaveRequest.status == status_filter)
    if leave_year_id is not None:
        statement = statement.where(LeaveRequest.leave_year_id == leave_year_id)
    if date_from is not None:
        statement = statement.where(LeaveRequest.end_date >= date_from)
    if date_to is not None:
        statement = statement.where(LeaveRequest.start_date <= date_to)
    statement = (
        statement.order_by(LeaveRequest.submitted_at.desc(), LeaveRequest.id.desc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 100))
    )
    requests = (await session.scalars(statement)).all()
    if not requests:
        return []

    types = {
        leave_type.id: leave_type
        for leave_type in (
            await session.scalars(
                select(LeaveType).where(
                    LeaveType.id.in_({row.leave_type_id for row in requests})
                )
            )
        ).all()
    }
    return [_summary(row, types[row.leave_type_id]) for row in requests]


@router.post("/{request_id}/cancel", response_model=DecisionResult)
async def cancel_leave_request(
    request_id: int,
    payload: CancelIn,
    current: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> DecisionResult:
    """Any signed-in user may call this; the service applies the rules."""
    request = await cancel_request(session, request_id, current, payload.comment)
    return DecisionResult(request_id=request.id, status=RequestStatus(request.status))


@router.get("", response_model=list[AdminRequestRow], dependencies=ADMIN_ONLY)
async def list_all_leave_requests(
    status_filter: RequestStatus | None = Query(default=None, alias="status"),
    employee_id: int | None = None,
    division_id: int | None = None,
    leave_year_id: int | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[AdminRequestRow]:
    """Every request (ADMIN only). Three queries in total, whatever the size."""
    statement = select(LeaveRequest)
    if status_filter is not None:
        statement = statement.where(LeaveRequest.status == status_filter)
    if employee_id is not None:
        statement = statement.where(LeaveRequest.employee_id == employee_id)
    if leave_year_id is not None:
        statement = statement.where(LeaveRequest.leave_year_id == leave_year_id)
    if division_id is not None:
        statement = statement.join(
            Employee, Employee.id == LeaveRequest.employee_id
        ).where(Employee.division_id == division_id)
    if date_from is not None:
        statement = statement.where(LeaveRequest.end_date >= date_from)
    if date_to is not None:
        statement = statement.where(LeaveRequest.start_date <= date_to)
    statement = (
        statement.order_by(LeaveRequest.submitted_at.desc(), LeaveRequest.id.desc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 100))
    )
    requests = (await session.scalars(statement)).all()
    if not requests:
        return []

    employees = {
        person.id: person
        for person in (
            await session.scalars(
                select(Employee).where(
                    Employee.id.in_({row.employee_id for row in requests})
                )
            )
        ).all()
    }
    types = {
        leave_type.id: leave_type
        for leave_type in (
            await session.scalars(
                select(LeaveType).where(
                    LeaveType.id.in_({row.leave_type_id for row in requests})
                )
            )
        ).all()
    }
    return [
        AdminRequestRow(
            **_summary(row, types[row.leave_type_id]).model_dump(),
            employee_id=employees[row.employee_id].id,
            employee_code=employees[row.employee_id].employee_code,
            employee_name=employees[row.employee_id].full_name,
        )
        for row in requests
    ]


@router.get("/{request_id}", response_model=LeaveRequestDetail)
async def get_leave_request(
    request_id: int,
    current: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> LeaveRequestDetail:
    request = await _visible_or_404(session, request_id, current)
    return await _detail(session, request, current)


@router.get("/{request_id}/attachment")
async def download_attachment(
    request_id: int,
    current: Employee = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    request = await _visible_or_404(session, request_id, current)
    if not request.attachment_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This request has no attachment.")

    path = storage.open_path(request.attachment_url)
    suffix = path.suffix.lower().lstrip(".")
    filename = f"leave-request-{request.id}.{suffix}"
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(suffix, "application/octet-stream"),
        filename=filename,
    )
