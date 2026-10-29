"""Reporting queries shared by the JSON and CSV endpoints (NFR-4).

Both endpoints call the SAME filter builder, so they can never disagree.
JSON uses 3 queries (rows, count, summary) whatever the row count; the CSV export
streams batches of 1000 rows and adds one query per batch.

Every export is audited by the ROUTER (see routers/reports.py) and the audit
row is committed BEFORE the first byte is streamed — see D-146.
"""

import csv
import datetime
import io
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, literal_column, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.models.department import Department
from app.models.division import Division
from app.models.employee import Employee
from app.models.leave_balance import LeaveBalance
from app.models.leave_request import LeaveRequest, LeaveRequestApproval
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear
from app.services.report_rules import (
    ReportError,
    csv_safe,
    format_decimal,
    org_local_iso,
    validate_filters,
)

BATCH_SIZE = 1000


@dataclass(frozen=True)
class BalanceFilters:
    leave_year_id: int | None = None
    division_id: int | None = None
    department_id: int | None = None
    employee_id: int | None = None
    leave_type_id: int | None = None
    include_inactive_employees: bool = False


@dataclass(frozen=True)
class HistoryFilters:
    division_id: int | None = None
    department_id: int | None = None
    employee_id: int | None = None
    leave_type_id: int | None = None
    status: str | None = None
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None
    leave_year_id: int | None = None
    include_inactive_employees: bool = False
    include_reason: bool = False


# --- shared pieces ---------------------------------------------------------


async def active_year_id(session: AsyncSession) -> int | None:
    return await session.scalar(
        select(LeaveYear.id).where(LeaveYear.is_active.is_(True)).limit(1)
    )


async def resolve_leave_year_id(
    session: AsyncSession, leave_year_id: int | None
) -> int | None:
    if leave_year_id is not None:
        year = await session.get(LeaveYear, leave_year_id)
        if year is None:
            raise ReportError(f"Leave year {leave_year_id} not found.", 400)
        return year.id
    return await active_year_id(session)


async def check_department_belongs(
    session: AsyncSession, division_id: int | None, department_id: int | None
) -> None:
    if division_id is None or department_id is None:
        return
    department = await session.get(Department, department_id)
    if department is None:
        raise ReportError(f"Department {department_id} not found.", 400)
    if department.division_id != division_id:
        raise ReportError(
            f"Department {department_id} belongs to division "
            f"{department.division_id}, not division {division_id}.",
            400,
        )


# --- balances --------------------------------------------------------------


def _balance_statement(filters: BalanceFilters, leave_year_id: int | None):
    statement = (
        select(
            Employee.employee_code,
            Employee.full_name,
            Division.name,
            Department.name,
            LeaveType.code,
            LeaveType.name,
            LeaveYear.name,
            LeaveBalance.allocated,
            LeaveBalance.carried_forward,
            LeaveBalance.used,
            LeaveBalance.pending,
        )
        .join(Employee, Employee.id == LeaveBalance.employee_id)
        .join(Division, Division.id == Employee.division_id)
        .join(Department, Department.id == Employee.department_id)
        .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
        .join(LeaveYear, LeaveYear.id == LeaveBalance.leave_year_id)
        .where(LeaveBalance.leave_year_id == leave_year_id)
    )
    if not filters.include_inactive_employees:
        statement = statement.where(Employee.is_active.is_(True))
    if filters.division_id is not None:
        statement = statement.where(Employee.division_id == filters.division_id)
    if filters.department_id is not None:
        statement = statement.where(Employee.department_id == filters.department_id)
    if filters.employee_id is not None:
        statement = statement.where(Employee.id == filters.employee_id)
    if filters.leave_type_id is not None:
        statement = statement.where(LeaveType.id == filters.leave_type_id)
    return statement.order_by(
        Division.name, Department.name, Employee.employee_code, LeaveType.code
    )


def _balance_row(row) -> dict:
    (
        code, name, division, department, type_code, type_name, year_name,
        allocated, carried, used, pending,
    ) = row
    available = Decimal(allocated) + Decimal(carried) - Decimal(used) - Decimal(pending)
    return {
        "employee_code": code,
        "employee_name": name,
        "division": division,
        "department": department,
        "leave_type_code": type_code,
        "leave_type_name": type_name,
        "leave_year": year_name,
        "allocated": allocated,
        "carried_forward": carried,
        "used": used,
        "pending": pending,
        "available": available,
    }


async def balance_rows(
    session: AsyncSession, filters: BalanceFilters, leave_year_id: int | None
) -> list[dict]:
    rows = (await session.execute(_balance_statement(filters, leave_year_id))).all()
    return [_balance_row(row) for row in rows]


async def balance_page(
    session: AsyncSession,
    filters: BalanceFilters,
    leave_year_id: int | None,
    limit: int,
    offset: int,
) -> list[dict]:
    statement = _balance_statement(filters, leave_year_id).limit(limit).offset(offset)
    rows = (await session.execute(statement)).all()
    return [_balance_row(row) for row in rows]


async def balance_count(
    session: AsyncSession, filters: BalanceFilters, leave_year_id: int | None
) -> int:
    subquery = _balance_statement(filters, leave_year_id).subquery()
    return await session.scalar(select(func.count()).select_from(subquery)) or 0


async def balance_summary(
    session: AsyncSession, filters: BalanceFilters, leave_year_id: int | None
) -> dict:
    subquery = _balance_statement(filters, leave_year_id).subquery()
    row = (
        await session.execute(
            select(
                func.count(),
                func.coalesce(func.sum(subquery.c.allocated), 0),
                func.coalesce(func.sum(subquery.c.carried_forward), 0),
                func.coalesce(func.sum(subquery.c.used), 0),
                func.coalesce(func.sum(subquery.c.pending), 0),
            )
        )
    ).one()
    count, allocated, carried, used, pending = row
    available = Decimal(allocated) + Decimal(carried) - Decimal(used) - Decimal(pending)
    return {
        "row_count": count,
        "allocated": str(format_decimal(allocated)),
        "carried_forward": str(format_decimal(carried)),
        "used": str(format_decimal(used)),
        "pending": str(format_decimal(pending)),
        "available": str(format_decimal(available)),
    }


BALANCE_HEADER = [
    "Employee code", "Employee name", "Division", "Department",
    "Leave type code", "Leave type", "Leave year",
    "Allocated", "Carried forward", "Used", "Pending", "Available",
]


def balance_csv_row(row: dict) -> list:
    return [
        csv_safe(row["employee_code"]),
        csv_safe(row["employee_name"]),
        csv_safe(row["division"]),
        csv_safe(row["department"]),
        csv_safe(row["leave_type_code"]),
        csv_safe(row["leave_type_name"]),
        csv_safe(row["leave_year"]),
        format_decimal(row["allocated"]),
        format_decimal(row["carried_forward"]),
        format_decimal(row["used"]),
        format_decimal(row["pending"]),
        format_decimal(row["available"]),
    ]


async def iter_balance_batches(
    session: AsyncSession, filters: BalanceFilters, leave_year_id: int | None
):
    offset = 0
    while True:
        batch = await balance_page(
            session, filters, leave_year_id, BATCH_SIZE, offset
        )
        if not batch:
            return
        yield batch
        if len(batch) < BATCH_SIZE:
            return
        offset += BATCH_SIZE


# --- history ---------------------------------------------------------------


def _history_statement(filters: HistoryFilters):
    approver = aliased(Employee)
    approvals_text = (
        select(
            func.string_agg(
                approver.full_name.concat(": ").concat(LeaveRequestApproval.status),
                literal_column("'; '"),
            )
        )
        .select_from(LeaveRequestApproval)
        .join(approver, approver.id == LeaveRequestApproval.approver_id)
        .where(LeaveRequestApproval.leave_request_id == LeaveRequest.id)
        .correlate(LeaveRequest)
        .scalar_subquery()
    )
    canceller = aliased(Employee)

    columns = [
        LeaveRequest.id,
        Employee.employee_code,
        Employee.full_name,
        Division.name,
        Department.name,
        LeaveType.code,
        LeaveType.name,
        LeaveRequest.start_date,
        LeaveRequest.end_date,
        LeaveRequest.day_type,
        LeaveRequest.chargeable_days,
        LeaveRequest.status,
        LeaveRequest.submitted_at,
        LeaveRequest.final_decided_at,
        LeaveRequest.cancelled_at,
        canceller.full_name,
        approvals_text,
    ]
    if filters.include_reason:
        columns.append(LeaveRequest.reason)

    statement = (
        select(*columns)
        .join(Employee, Employee.id == LeaveRequest.employee_id)
        .join(Division, Division.id == Employee.division_id)
        .join(Department, Department.id == Employee.department_id)
        .join(LeaveType, LeaveType.id == LeaveRequest.leave_type_id)
        .outerjoin(canceller, canceller.id == LeaveRequest.cancelled_by_id)
    )
    if not filters.include_inactive_employees:
        statement = statement.where(Employee.is_active.is_(True))
    if filters.division_id is not None:
        statement = statement.where(Employee.division_id == filters.division_id)
    if filters.department_id is not None:
        statement = statement.where(Employee.department_id == filters.department_id)
    if filters.employee_id is not None:
        statement = statement.where(Employee.id == filters.employee_id)
    if filters.leave_type_id is not None:
        statement = statement.where(LeaveType.id == filters.leave_type_id)
    if filters.status is not None:
        statement = statement.where(LeaveRequest.status == filters.status)
    if filters.leave_year_id is not None:
        statement = statement.where(LeaveRequest.leave_year_id == filters.leave_year_id)
    # "date_from/date_to" means OVERLAP, not containment (see DECISIONS D-122).
    if filters.date_from is not None:
        statement = statement.where(LeaveRequest.end_date >= filters.date_from)
    if filters.date_to is not None:
        statement = statement.where(LeaveRequest.start_date <= filters.date_to)
    return statement.order_by(LeaveRequest.start_date.desc(), LeaveRequest.id.desc())


def _history_row(row, include_reason: bool) -> dict:
    values = list(row)
    data = {
        "request_id": values[0],
        "employee_code": values[1],
        "employee_name": values[2],
        "division": values[3],
        "department": values[4],
        "leave_type_code": values[5],
        "leave_type_name": values[6],
        "start_date": values[7],
        "end_date": values[8],
        "day_type": values[9],
        "chargeable_days": values[10],
        "status": values[11],
        "submitted_at": values[12],
        "final_decided_at": values[13],
        "cancelled_at": values[14],
        "cancelled_by": values[15],
        "approvals": values[16],
    }
    if include_reason:
        data["reason"] = values[17]
    return data


async def history_page(
    session: AsyncSession, filters: HistoryFilters, limit: int, offset: int
) -> list[dict]:
    statement = _history_statement(filters).limit(limit).offset(offset)
    rows = (await session.execute(statement)).all()
    return [_history_row(row, filters.include_reason) for row in rows]


async def history_count(
    session: AsyncSession, filters: HistoryFilters
) -> int:
    subquery = _history_statement(filters).subquery()
    return await session.scalar(select(func.count()).select_from(subquery)) or 0


async def history_summary(
    session: AsyncSession, filters: HistoryFilters
) -> dict:
    subquery = _history_statement(filters).subquery()
    rows = (
        await session.execute(
            select(
                subquery.c.status,
                func.count(),
                func.coalesce(func.sum(subquery.c.chargeable_days), 0),
            ).group_by(subquery.c.status)
        )
    ).all()
    by_status = {
        status: {
            "requests": count,
            "days": format_decimal(days),
        }
        for status, count, days in rows
    }
    total_requests = sum(item["requests"] for item in by_status.values())
    total_days = sum(
        (Decimal(item["days"]) for item in by_status.values()), Decimal("0")
    )
    return {
        "row_count": total_requests,
        "total_days": format_decimal(total_days),
        "by_status": by_status,
    }


HISTORY_HEADER_BASE = [
    "Request id", "Employee code", "Employee name", "Division", "Department",
    "Leave type code", "Leave type", "Start date", "End date", "Day type",
    "Chargeable days", "Status", "Submitted at", "Decided at", "Cancelled at",
    "Cancelled by", "Approvals",
]


def history_header(include_reason: bool) -> list[str]:
    return HISTORY_HEADER_BASE + (["Reason"] if include_reason else [])


def history_csv_row(row: dict, include_reason: bool, tz_name: str) -> list:
    cells = [
        row["request_id"],
        csv_safe(row["employee_code"]),
        csv_safe(row["employee_name"]),
        csv_safe(row["division"]),
        csv_safe(row["department"]),
        csv_safe(row["leave_type_code"]),
        csv_safe(row["leave_type_name"]),
        row["start_date"].isoformat(),
        row["end_date"].isoformat(),
        csv_safe(row["day_type"]),
        format_decimal(row["chargeable_days"]),
        csv_safe(row["status"]),
        org_local_iso(row["submitted_at"], tz_name),
        org_local_iso(row["final_decided_at"], tz_name),
        org_local_iso(row["cancelled_at"], tz_name),
        csv_safe(row["cancelled_by"]),
        csv_safe(row["approvals"]),
    ]
    if include_reason:
        cells.append(csv_safe(row.get("reason")))
    return cells


async def iter_history_batches(session: AsyncSession, filters: HistoryFilters):
    offset = 0
    while True:
        batch = await history_page(session, filters, BATCH_SIZE, offset)
        if not batch:
            return
        yield batch
        if len(batch) < BATCH_SIZE:
            return
        offset += BATCH_SIZE


# --- CSV chunks ------------------------------------------------------------


def csv_chunk(header: list[str], rows: list[list]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    if header:
        writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


async def export_balance_csv(
    session: AsyncSession, filters: BalanceFilters, leave_year_id: int | None
):
    """Yield UTF-8 CSV chunks, starting with the BOM so Excel shows Bengali."""
    yield b"\xef\xbb\xbf" + csv_chunk(BALANCE_HEADER, [])
    async for batch in iter_balance_batches(session, filters, leave_year_id):
        yield csv_chunk([], [balance_csv_row(row) for row in batch])


async def export_history_csv(session: AsyncSession, filters: HistoryFilters):
    tz_name = settings.org_timezone
    yield b"\xef\xbb\xbf" + csv_chunk(history_header(filters.include_reason), [])
    async for batch in iter_history_batches(session, filters):
        yield csv_chunk(
            [],
            [
                history_csv_row(row, filters.include_reason, tz_name)
                for row in batch
            ],
        )
