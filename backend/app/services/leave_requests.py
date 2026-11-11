"""Leave request evaluation and submission service."""

import datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.employee import Employee
from app.models.employee_approver import EmployeeApprover
from app.models.leave_balance import EmployeeLeaveType, LeaveBalance
from app.models.leave_request import (
    ApprovalStatus,
    CheckProblem,
    LeaveRequest,
    LeaveRequestAllocation,
    LeaveRequestApproval,
    LeaveRequestCheck,
    RequestStatus,
    YearBalanceRead,
    YearSplitRead,
)
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear
from app.services.calendar import build_preview
from app.services.audit import balance_snapshot, record
from app.services.locking import assert_years_open, lock_years_shared
from app.services.notifications import build_facts, enqueue_events
from app.services.day_calc import DayCalcError, DayType
from app.services.request_rules import (
    RequestRange,
    RequestRuleError,
    ranges_conflict,
    split_days_by_leave_year,
    years_for_days,
)

APPROVAL_BLOCKING_STATUSES = (RequestStatus.PENDING, RequestStatus.APPROVED)


def _problem(code: str, message: str, http_status: int) -> CheckProblem:
    return CheckProblem(code=code, message=message, status=http_status)


async def active_approvers(session: AsyncSession, employee_id: int) -> list[Employee]:
    return list(
        (
            await session.scalars(
                select(Employee)
                .join(EmployeeApprover, EmployeeApprover.approver_id == Employee.id)
                .where(
                    EmployeeApprover.employee_id == employee_id,
                    EmployeeApprover.is_active.is_(True),
                    Employee.is_active.is_(True),
                )
                .order_by(Employee.id)
            )
        ).all()
    )


async def evaluate(
    session: AsyncSession,
    employee: Employee,
    leave_type_id: int,
    start_date: datetime.date,
    end_date: datetime.date,
    day_type: DayType,
    has_attachment: bool,
) -> LeaveRequestCheck:
    """Validate a leave request and return day splits, balance impacts, and any problems."""
    problems: list[CheckProblem] = []
    check = LeaveRequestCheck(
        employee_id=employee.id,
        leave_type_id=leave_type_id,
        start_date=start_date,
        end_date=end_date,
        day_type=day_type,
        chargeable_days=Decimal("0"),
    )

    try:
        preview = await build_preview(
            session, employee, start_date, end_date, day_type
        )
    except DayCalcError as exc:
        check.problems = [_problem("invalid_dates", str(exc), 400)]
        return check

    check.weekend_days = preview.weekend_days
    check.days = preview.days
    check.chargeable_days = preview.chargeable_days

    leave_type = await session.get(LeaveType, leave_type_id)
    if leave_type is None:
        check.problems = [_problem("leave_type_not_found", "Leave type not found.", 400)]
        return check
    check.leave_type_id = leave_type.id

    all_years = list((await session.scalars(select(LeaveYear))).all())
    try:
        touched_years = years_for_days(preview.days, all_years)
        per_year = split_days_by_leave_year(preview.days, all_years, day_type)
    except RequestRuleError as exc:
        check.problems = [_problem("date_outside_leave_years", str(exc), 400)]
        return check

    if day_type is not DayType.FULL_DAY and not leave_type.allow_half_day:
        problems.append(
            _problem(
                "half_day_not_allowed",
                f"Leave type '{leave_type.code}' does not allow half days.",
                400,
            )
        )

    if not leave_type.is_active:
        problems.append(
            _problem(
                "leave_type_inactive",
                f"Leave type '{leave_type.code}' is inactive.",
                400,
            )
        )

    touched_ids = [year.id for year in touched_years]
    assignments = set(
        (
            await session.scalars(
                select(EmployeeLeaveType.leave_year_id).where(
                    EmployeeLeaveType.employee_id == employee.id,
                    EmployeeLeaveType.leave_type_id == leave_type.id,
                    EmployeeLeaveType.leave_year_id.in_(touched_ids),
                )
            )
        ).all()
    )
    balances = {
        balance.leave_year_id: balance
        for balance in (
            await session.scalars(
                select(LeaveBalance).where(
                    LeaveBalance.employee_id == employee.id,
                    LeaveBalance.leave_type_id == leave_type.id,
                    LeaveBalance.leave_year_id.in_(touched_ids),
                )
            )
        ).all()
    }

    for year in touched_years:
        if year.is_closed:
            problems.append(
                _problem(
                    "year_closed",
                    f"Leave year '{year.name}' is closed.",
                    400,
                )
            )
        if year.id not in assignments:
            problems.append(
                _problem(
                    "not_assigned",
                    f"'{leave_type.code}' is not assigned to you for leave year "
                    f"'{year.name}'.",
                    400,
                )
            )

        days = per_year.get(year.id, Decimal("0"))
        balance = balances.get(year.id)
        before = balance.available if balance is not None else Decimal("0")
        after = before - days
        check.per_year.append(
            YearSplitRead(
                leave_year_id=year.id, leave_year_name=year.name, days=days
            )
        )
        check.balances.append(
            YearBalanceRead(
                leave_year_id=year.id,
                leave_year_name=year.name,
                available_before=before,
                days=days,
                available_after=after,
            )
        )
        if after < 0:
            problems.append(
                _problem(
                    "insufficient_balance",
                    f"Not enough '{leave_type.code}' balance in leave year "
                    f"'{year.name}': available {before}, requested {days}.",
                    409,
                )
            )

    if check.chargeable_days <= 0:
        problems.append(
            _problem(
                "no_working_days",
                "There are no working days in this range (only weekends and/or "
                "holidays).",
                400,
            )
        )

    new_range = RequestRange(start_date, end_date, day_type)
    existing = (
        await session.scalars(
            select(LeaveRequest).where(
                LeaveRequest.employee_id == employee.id,
                LeaveRequest.status.in_(APPROVAL_BLOCKING_STATUSES),
            )
        )
    ).all()
    for row in existing:
        if ranges_conflict(
            RequestRange(row.start_date, row.end_date, row.day_type), new_range
        ):
            problems.append(
                _problem(
                    "overlap",
                    f"This overlaps an existing {row.status.lower()} request "
                    f"({row.start_date}..{row.end_date}).",
                    409,
                )
            )
            break

    approvers = await active_approvers(session, employee.id)
    if not approvers:
        problems.append(
            _problem(
                "no_approver",
                "You have no active approver. Ask an admin to assign one before "
                "submitting leave.",
                400,
            )
        )

    check.problems = problems
    check.can_submit = not problems
    return check


async def submit(
    session: AsyncSession,
    employee: Employee,
    leave_type_id: int,
    start_date: datetime.date,
    end_date: datetime.date,
    day_type: DayType,
    reason: str,
    attachment_url: str | None,
) -> LeaveRequest:
    """Create a pending leave request with allocations, approval rows, and reserved balances."""
    probe = await evaluate(
        session,
        employee,
        leave_type_id,
        start_date,
        end_date,
        day_type,
        has_attachment=attachment_url is not None,
    )
    year_ids = sorted({balance.leave_year_id for balance in probe.balances})

    # Lock order: leave years (SHARED) -> employee row -> balance rows.
    assert_years_open(await lock_years_shared(session, year_ids))

    await session.execute(
        select(Employee.id).where(Employee.id == employee.id).with_for_update()
    )

    locked_balances: dict[int, LeaveBalance] = {}
    if year_ids:
        rows = (
            await session.scalars(
                select(LeaveBalance)
                .where(
                    LeaveBalance.employee_id == employee.id,
                    LeaveBalance.leave_type_id == leave_type_id,
                    LeaveBalance.leave_year_id.in_(year_ids),
                )
                .order_by(LeaveBalance.leave_year_id)
                .with_for_update()
            )
        ).all()
        locked_balances = {row.leave_year_id: row for row in rows}

    check = await evaluate(
        session,
        employee,
        leave_type_id,
        start_date,
        end_date,
        day_type,
        has_attachment=attachment_url is not None,
    )
    if check.problems:
        await session.rollback()
        first = check.problems[0]
        raise HTTPException(first.status, first.message)

    year_of_start = next(
        year
        for year in (await session.scalars(select(LeaveYear))).all()
        if year.start_date <= start_date <= year.end_date
    )

    request = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=leave_type_id,
        leave_year_id=year_of_start.id,
        start_date=start_date,
        end_date=end_date,
        day_type=day_type,
        chargeable_days=check.chargeable_days,
        reason=reason,
        attachment_url=attachment_url,
        status=RequestStatus.PENDING,
    )
    session.add(request)
    await session.flush()

    for split in check.per_year:
        if split.days > 0:
            session.add(
                LeaveRequestAllocation(
                    leave_request_id=request.id,
                    leave_year_id=split.leave_year_id,
                    days=split.days,
                )
            )

    approvers = await active_approvers(session, employee.id)
    approval_rows: list[LeaveRequestApproval] = []
    for approver in approvers:
        approval_row = LeaveRequestApproval(
            leave_request_id=request.id,
            approver_id=approver.id,
            status=ApprovalStatus.PENDING,
        )
        session.add(approval_row)
        approval_rows.append(approval_row)

    before_balances = balance_snapshot(locked_balances)
    for balance_read in check.balances:
        if balance_read.days > 0:
            locked_balances[balance_read.leave_year_id].pending += balance_read.days

    await session.flush()

    import secrets
    from app.models.auth_tokens import ApprovalActionToken
    from app.services.security_rules import hash_token

    approver_tokens: dict[int, str] = {}
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    expires_at = now_utc + datetime.timedelta(days=14)
    for row in approval_rows:
        if row.id is not None:
            raw_token = secrets.token_urlsafe(32)
            session.add(
                ApprovalActionToken(
                    approval_id=row.id,
                    token_hash=hash_token(raw_token),
                    action="APPROVE",
                    expires_at=expires_at,
                )
            )
            approver_tokens[row.approver_id] = raw_token

    facts = await build_facts(
        session,
        request,
        extra={
            "actor_email": employee.email,
            "approver_tokens": approver_tokens,
        },
    )
    await enqueue_events(session, "SUBMITTED", facts)

    await record(
        session,
        employee.id,
        "leave_request",
        request.id,
        "SUBMIT",
        new={
            "leave_type_id": leave_type_id,
            "leave_year_id": year_of_start.id,
            "start_date": start_date,
            "end_date": end_date,
            "day_type": day_type,
            "chargeable_days": check.chargeable_days,
            "status": "PENDING",
            "balances": balance_snapshot(locked_balances),
        },
        old={"balances": before_balances},
    )

    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The balance changed while submitting. Please try again.",
        ) from None


    await session.refresh(request)
    return request
