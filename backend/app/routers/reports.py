import datetime
import zoneinfo
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlmodel import SQLModel

from app.core.config import settings
from app.core.deps import get_current_user, require_roles
from app.db.session import get_session
from app.models.employee import Employee, Role
from app.services.audit import record
from app.models.leave_request import RequestStatus
from app.services.report_rules import ReportError, export_filename, validate_filters
from app.services.reports import (
    BALANCE_HEADER,
    csv_chunk,
    BalanceFilters,
    HistoryFilters,
    balance_count,
    balance_page,
    balance_summary,
    check_department_belongs,
    export_balance_csv,
    export_history_csv,
    history_count,
    history_page,
    history_summary,
    resolve_leave_year_id,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/reports", tags=["reports"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]


class BalanceRow(SQLModel):
    employee_code: str
    employee_name: str
    division: str
    department: str
    leave_type_code: str
    leave_type_name: str
    leave_year: str
    allocated: Decimal
    carried_forward: Decimal
    used: Decimal
    pending: Decimal
    available: Decimal


class BalanceReport(SQLModel):
    rows: list[BalanceRow]
    total: int
    limit: int
    offset: int
    leave_year_id: int | None = None
    summary: dict


class HistoryRow(SQLModel):
    request_id: int
    employee_code: str
    employee_name: str
    division: str
    department: str
    leave_type_code: str
    leave_type_name: str
    start_date: datetime.date
    end_date: datetime.date
    day_type: str
    chargeable_days: Decimal
    status: str
    submitted_at: datetime.datetime
    final_decided_at: datetime.datetime | None = None
    cancelled_at: datetime.datetime | None = None
    cancelled_by: str | None = None
    approvals: str | None = None
    reason: str | None = None


class HistoryReport(SQLModel):
    rows: list[HistoryRow]
    total: int
    limit: int
    offset: int
    summary: dict


def _today() -> datetime.date:
    return datetime.datetime.now(zoneinfo.ZoneInfo(settings.org_timezone)).date()


@router.get("/balances", response_model=BalanceReport, dependencies=ADMIN_ONLY)
async def balances_json(
    leave_year_id: int | None = None,
    division_id: int | None = None,
    department_id: int | None = None,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    include_inactive_employees: bool = False,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> BalanceReport:
    validate_filters(limit=limit, offset=offset)
    await check_department_belongs(session, division_id, department_id)
    year_id = await resolve_leave_year_id(session, leave_year_id)

    filters = BalanceFilters(
        leave_year_id=year_id,
        division_id=division_id,
        department_id=department_id,
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        include_inactive_employees=include_inactive_employees,
    )
    if year_id is None:
        rows, total = [], 0
    else:
        rows = await balance_page(session, filters, year_id, limit, offset)
        total = await balance_count(session, filters, year_id)
    summary = (
        await balance_summary(session, filters, year_id)
        if year_id is not None
        else {"row_count": 0}
    )
    return BalanceReport(
        rows=[BalanceRow(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        leave_year_id=year_id,
        summary=summary,
    )


@router.get("/balances/export", dependencies=ADMIN_ONLY)
async def balances_export(
    leave_year_id: int | None = None,
    division_id: int | None = None,
    department_id: int | None = None,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    include_inactive_employees: bool = False,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> StreamingResponse:
    validate_filters()
    await check_department_belongs(session, division_id, department_id)
    year_id = await resolve_leave_year_id(session, leave_year_id)
    filters = BalanceFilters(
        leave_year_id=year_id,
        division_id=division_id,
        department_id=department_id,
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        include_inactive_employees=include_inactive_employees,
    )

    if year_id is not None:
        total = await balance_count(session, filters, year_id)
        if total > settings.export_max_rows:
            raise ReportError(
                f"This report has {total} rows, more than the "
                f"{settings.export_max_rows}-row export limit. Please narrow the "
                "filters.",
                400,
            )

    # Audit BEFORE streaming and commit it here: personal data is about to
    # leave the system, and the record must exist even if the browser aborts
    # the download halfway (D-146).
    await record(
        session, actor.id, "report", None, "REPORT_EXPORT",
        new={
            "report": "balances",
            "filters": {
                "leave_year_id": year_id,
                "division_id": division_id,
                "department_id": department_id,
                "employee_id": employee_id,
                "leave_type_id": leave_type_id,
                "include_inactive_employees": include_inactive_employees,
            },
            "row_count": total if year_id is not None else 0,
            "include_reason": False,
            "source": "CSV export of the balances report",
        },
    )
    await session.commit()

    filename = export_filename("balances", _today())
    return StreamingResponse(
        export_balance_csv(session, filters, year_id) if year_id is not None
        else _empty_csv(BALANCE_HEADER),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/history", response_model=HistoryReport, dependencies=ADMIN_ONLY)
async def history_json(
    division_id: int | None = None,
    department_id: int | None = None,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    status_filter: RequestStatus | None = Query(default=None, alias="status"),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    leave_year_id: int | None = None,
    include_inactive_employees: bool = False,
    include_reason: bool = False,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> HistoryReport:
    validate_filters(date_from=date_from, date_to=date_to, limit=limit, offset=offset)
    await check_department_belongs(session, division_id, department_id)

    filters = HistoryFilters(
        division_id=division_id,
        department_id=department_id,
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        status=status_filter.value if status_filter else None,
        date_from=date_from,
        date_to=date_to,
        leave_year_id=leave_year_id,
        include_inactive_employees=include_inactive_employees,
        include_reason=include_reason,
    )
    rows = await history_page(session, filters, limit, offset)
    total = await history_count(session, filters)
    summary = await history_summary(session, filters)
    report = HistoryReport(
        rows=[HistoryRow(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
        summary=summary,
    )
    body = report.model_dump(mode="json")
    if not include_reason:
        # The column is opt-in (D-121), so it is not even present in the JSON.
        for row in body["rows"]:
            row.pop("reason", None)
    return JSONResponse(content=body)


@router.get("/history/export", dependencies=ADMIN_ONLY)
async def history_export(
    division_id: int | None = None,
    department_id: int | None = None,
    employee_id: int | None = None,
    leave_type_id: int | None = None,
    status_filter: RequestStatus | None = Query(default=None, alias="status"),
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    leave_year_id: int | None = None,
    include_inactive_employees: bool = False,
    include_reason: bool = False,
    session: AsyncSession = Depends(get_session),
    actor: Employee = Depends(get_current_user),
) -> StreamingResponse:
    validate_filters(date_from=date_from, date_to=date_to)
    await check_department_belongs(session, division_id, department_id)

    filters = HistoryFilters(
        division_id=division_id,
        department_id=department_id,
        employee_id=employee_id,
        leave_type_id=leave_type_id,
        status=status_filter.value if status_filter else None,
        date_from=date_from,
        date_to=date_to,
        leave_year_id=leave_year_id,
        include_inactive_employees=include_inactive_employees,
        include_reason=include_reason,
    )
    total = await history_count(session, filters)
    if total > settings.export_max_rows:
        raise ReportError(
            f"This report has {total} rows, more than the "
            f"{settings.export_max_rows}-row export limit. Please narrow the "
            "filters.",
            400,
        )

    await record(
        session, actor.id, "report", None, "REPORT_EXPORT",
        new={
            "report": "history",
            "filters": {
                "division_id": division_id,
                "department_id": department_id,
                "employee_id": employee_id,
                "leave_type_id": leave_type_id,
                "status": status_filter.value if status_filter else None,
                "date_from": date_from,
                "date_to": date_to,
                "leave_year_id": leave_year_id,
                "include_inactive_employees": include_inactive_employees,
            },
            "row_count": total,
            "include_reason": include_reason,
            "source": "CSV export of the history report",
        },
    )
    await session.commit()

    filename = export_filename("history", _today())
    return StreamingResponse(
        export_history_csv(session, filters),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _empty_csv(header: list[str]):
    yield b"\xef\xbb\xbf" + csv_chunk(header, [])
