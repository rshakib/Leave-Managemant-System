"""Year-end closing and carry-forward (FR-LT-4).

LOCKING (the important part)
============================
Closing changes MANY balances at once and cannot be undone, so safety comes
first. The gate is the `leave_year` row itself:

* Every writer of `leave_balance` — and every creator of a leave request — takes
  a **SHARED** lock (`SELECT ... FOR SHARE`) on the leave-year rows it is about
  to touch, and THEN re-checks `is_closed`. Several writers may hold a shared
  lock at the same time, so ordinary work is not serialised.
* Closing takes an **EXCLUSIVE** lock (`SELECT ... FOR UPDATE`) on the from-year
  and the to-year. While a closing holds it, every writer for those years waits;
  while a writer holds a shared lock, the closing waits.

So exactly one of these happens: the writer finishes first and the closing then
sees its rows, or the closing finishes first and the writer wakes up to
`is_closed = true` and is refused (HTTP 409). Never "both succeeded".

* The ONE global lock order is: **leave years -> employee row -> balance rows**.
  Years are locked in ascending id order. A closing touches employee rows only
  *after* the year (through the `closed_by_id` / `processed_by` foreign keys,
  which take a KEY SHARE lock on the referenced employee), and `submit()` was
  changed to take the year BEFORE the employee row for exactly this reason: with
  the old order (employee first) a closing and a submission by the same employee
  could wait for each other and PostgreSQL killed one with "deadlock detected".
  With one order, no two transactions can wait for each other in a circle.

`approvals.act()` and `cancellations.cancel()` do not take this lock: a closed
year can never contain a PENDING request (closing is blocked while one exists,
and submissions into a closed year are refused), and cancelling an APPROVED
request that touches a closed year is already refused (DECISIONS D-104). A test
confirms both.

Deliberately NO email: FR-NOT-1 lists six events and the year-end closing is not
one of them (D-195). The result is not lost — the admin sees it in the closing
summary, the carry-forward log (GET /leave-years/{id}/carry-forwards) keeps every
row, and each employee sees their carried days on "My balances". Emailing every
employee at year end is a separate product decision, not an unfinished task.
"""

import datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.balance_adjustment import AdjustmentField, LeaveBalanceAdjustment
from app.models.employee import Employee
from app.models.leave_balance import EmployeeLeaveType, LeaveBalance
from app.models.leave_carry_forward import LeaveCarryForward
from app.models.leave_request import LeaveRequest, LeaveRequestAllocation, RequestStatus
from app.models.leave_type import LeaveType
from app.models.leave_year import LeaveYear
from app.services.closing_rules import (
    TWO_PLACES,
    closing_blockers,
    compute_carry,
    find_next_year,
    find_previous_year,
)
from app.services.audit import record
from app.services.locking import lock_years_exclusive

PREVIEW_ROW_LIMIT = 200


def _days(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(value).quantize(TWO_PLACES)


def _remaining(balance: LeaveBalance) -> Decimal:
    return _days(
        Decimal(balance.allocated)
        + Decimal(balance.carried_forward)
        - Decimal(balance.used)
        - Decimal(balance.pending)
    )


async def _all_years(session: AsyncSession, fresh: bool = False) -> list[LeaveYear]:
    statement = select(LeaveYear).order_by(LeaveYear.id)
    if fresh:
        statement = statement.execution_options(populate_existing=True)
    return list((await session.scalars(statement)).all())


async def _pending_request_count(session: AsyncSession, year_id: int) -> int:
    """Counted through the ALLOCATION rows, not `leave_request.leave_year_id`.

    A cross-year request stores only its start year in `leave_request`, but it
    holds days in BOTH years. Counting through `leave_request_allocation` finds
    any request that still owes days to this year, whatever its start year.
    """
    return (
        await session.scalar(
            select(func.count(func.distinct(LeaveRequest.id)))
            .select_from(LeaveRequest)
            .join(
                LeaveRequestAllocation,
                LeaveRequestAllocation.leave_request_id == LeaveRequest.id,
            )
            .where(
                LeaveRequestAllocation.leave_year_id == year_id,
                LeaveRequest.status == RequestStatus.PENDING,
            )
        )
        or 0
    )


async def _balances_with_details(
    session: AsyncSession, year_id: int, fresh: bool = False
) -> list:
    statement = (
        select(LeaveBalance, Employee, LeaveType)
        .join(Employee, Employee.id == LeaveBalance.employee_id)
        .join(LeaveType, LeaveType.id == LeaveBalance.leave_type_id)
        .where(LeaveBalance.leave_year_id == year_id)
        .order_by(Employee.employee_code, LeaveType.code)
    )
    if fresh:
        statement = statement.execution_options(populate_existing=True)
    return list((await session.execute(statement)).all())


async def _next_year_pairs(session: AsyncSession, next_year_id: int | None) -> set:
    if next_year_id is None:
        return set()
    rows = await session.scalars(
        select(EmployeeLeaveType).where(
            EmployeeLeaveType.leave_year_id == next_year_id
        )
    )
    return {(row.employee_id, row.leave_type_id) for row in rows.all()}


def _plan(rows, next_year_pairs, next_year_id) -> dict:
    """Turn balance rows into the closing plan (pure — no database)."""
    log_rows = []
    to_year_values = []
    totals: dict[int, dict] = {}
    preview = []
    skipped_inactive = 0
    missing_assignments = set()

    for balance, employee, leave_type in rows:
        remaining = _remaining(balance)
        split = compute_carry(
            remaining, leave_type.max_carry_forward_days, leave_type.carry_forward_allowed
        )
        if split is None:
            continue
        carried, forfeited = split
        if carried == 0 and forfeited == 0:
            continue  # nothing happened, so there is nothing to log

        if not employee.is_active:
            skipped_inactive += 1
            continue

        has_assignment = (employee.id, leave_type.id) in next_year_pairs
        if next_year_id is not None and carried > 0 and not has_assignment:
            missing_assignments.add(employee.id)

        log_rows.append(
            {
                "employee_id": employee.id,
                "leave_type_id": leave_type.id,
                "remaining_at_close": remaining,
                "carried_days": carried,
                "forfeited_days": forfeited,
            }
        )
        if carried > 0:
            to_year_values.append(
                {
                    "employee_id": employee.id,
                    "leave_type_id": leave_type.id,
                    "carried_forward": carried,
                }
            )

        bucket = totals.setdefault(
            leave_type.id,
            {
                "leave_type_id": leave_type.id,
                "leave_type_code": leave_type.code,
                "leave_type_name": leave_type.name,
                "employees": 0,
                "remaining": Decimal("0.00"),
                "carried": Decimal("0.00"),
                "forfeited": Decimal("0.00"),
            },
        )
        bucket["employees"] += 1
        bucket["remaining"] += remaining
        bucket["carried"] += carried
        bucket["forfeited"] += forfeited

        preview.append(
            {
                "employee_id": employee.id,
                "employee_code": employee.employee_code,
                "employee_name": employee.full_name,
                "leave_type_id": leave_type.id,
                "leave_type_code": leave_type.code,
                "leave_type_name": leave_type.name,
                "remaining": remaining,
                "carried": carried,
                "forfeited": forfeited,
                "has_next_year_assignment": has_assignment,
            }
        )

    total_carried = sum((row["carried_days"] for row in log_rows), Decimal("0.00"))
    total_forfeited = sum((row["forfeited_days"] for row in log_rows), Decimal("0.00"))
    return {
        "log_rows": log_rows,
        "to_year_values": to_year_values,
        "totals": list(totals.values()),
        "preview": preview,
        "skipped_inactive": skipped_inactive,
        "missing_assignments": len(missing_assignments),
        "fingerprint": {
            "rows": len(log_rows),
            "total_carried": str(_days(total_carried)),
            "total_forfeited": str(_days(total_forfeited)),
        },
    }


def _fingerprint_matches(expected: dict | None, actual: dict) -> bool:
    if not expected:
        return True
    return (
        str(expected.get("rows")) == str(actual["rows"])
        and str(expected.get("total_carried")) == actual["total_carried"]
        and str(expected.get("total_forfeited")) == actual["total_forfeited"]
    )


async def preview(
    session: AsyncSession,
    from_year_id: int,
    today: datetime.date | None = None,
    offset: int = 0,
    limit: int = PREVIEW_ROW_LIMIT,
) -> dict:
    """READ-ONLY dry run: what closing this year would do, and what stops it."""
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    year = await session.get(LeaveYear, from_year_id)
    if year is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Leave year {from_year_id} not found."
        )
    years = await _all_years(session)
    next_year = find_next_year(year, years)
    previous_year = find_previous_year(year, years)
    pending = await _pending_request_count(session, year.id)
    rows = await _balances_with_details(session, year.id)
    pairs = await _next_year_pairs(session, next_year.id if next_year else None)

    plan = _plan(rows, pairs, next_year.id if next_year else None)
    blockers, warnings = closing_blockers(
        year=year,
        today=today,
        next_year=next_year,
        previous_year=previous_year,
        pending_request_count=pending,
        missing_next_year_assignments=plan["missing_assignments"],
    )

    offset = max(0, offset)
    limit = min(max(1, limit), PREVIEW_ROW_LIMIT)
    page = plan["preview"][offset : offset + limit]
    return {
        "leave_year_id": year.id,
        "leave_year_name": year.name,
        "next_leave_year_id": next_year.id if next_year else None,
        "next_leave_year_name": next_year.name if next_year else None,
        "can_close": not blockers,
        "blockers": [
            {"code": b.code, "message": b.message, "http_status": b.http_status}
            for b in blockers
        ],
        "warnings": warnings,
        "totals_by_type": plan["totals"],
        "rows": page,
        "row_offset": offset,
        "row_limit": limit,
        "total_rows": len(plan["preview"]),
        "fingerprint": plan["fingerprint"],
    }


async def close_year(
    session: AsyncSession,
    from_year_id: int,
    actor: Employee,
    confirm_name: str,
    expected_fingerprint: dict | None,
    today: datetime.date | None = None,
) -> dict:
    """Close a leave year and move its remaining days into the next year.

    ONE transaction, all-or-nothing.
    """
    today = today or datetime.datetime.now(datetime.timezone.utc).date()
    now = datetime.datetime.now(datetime.timezone.utc)

    year = await session.get(LeaveYear, from_year_id)
    if year is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Leave year {from_year_id} not found."
        )
    next_year = find_next_year(year, await _all_years(session))

    # EXCLUSIVE lock on both years, ascending id. No employee rows are locked.
    await lock_years_exclusive(
        session, [year.id] + ([next_year.id] if next_year is not None else [])
    )

    # Re-read FRESH under the lock: another transaction may have changed these
    # rows while we waited for the lock (same trap as Phases 11 and 12).
    year = await session.scalar(
        select(LeaveYear)
        .where(LeaveYear.id == from_year_id)
        .execution_options(populate_existing=True)
    )
    years = await _all_years(session, fresh=True)
    next_year = find_next_year(year, years)
    previous_year = find_previous_year(year, years)

    pending = await _pending_request_count(session, year.id)
    rows = await _balances_with_details(session, year.id, fresh=True)
    pairs = await _next_year_pairs(session, next_year.id if next_year else None)

    plan = _plan(rows, pairs, next_year.id if next_year else None)
    blockers, _warnings = closing_blockers(
        year=year,
        today=today,
        next_year=next_year,
        previous_year=previous_year,
        pending_request_count=pending,
        missing_next_year_assignments=plan["missing_assignments"],
    )
    if blockers:
        first = blockers[0]
        raise HTTPException(first.http_status, first.message)

    if confirm_name != year.name:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Type the leave year name exactly ('{year.name}') to confirm.",
        )
    if not _fingerprint_matches(expected_fingerprint, plan["fingerprint"]):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The data changed since the preview. Please preview again.",
        )

    log_rows = plan["log_rows"]
    to_year_values = plan["to_year_values"]

    if log_rows:
        await session.execute(
            pg_insert(LeaveCarryForward).values(
                [
                    {**row, "from_leave_year_id": year.id, "to_leave_year_id": next_year.id,
                     "processed_at": now, "processed_by": actor.id}
                    for row in log_rows
                ]
            )
        )

    created = updated = 0
    if to_year_values:
        existing = set(
            (
                await session.execute(
                    select(
                        LeaveBalance.employee_id, LeaveBalance.leave_type_id
                    ).where(LeaveBalance.leave_year_id == next_year.id)
                )
            ).all()
        )
        created = sum(
            1
            for row in to_year_values
            if (row["employee_id"], row["leave_type_id"]) not in existing
        )
        updated = len(to_year_values) - created

        statement = pg_insert(LeaveBalance).values(
            [
                {
                    **row,
                    "leave_year_id": next_year.id,
                    "allocated": Decimal("0.00"),
                }
                for row in to_year_values
            ]
        )
        # ADD to what is already carried forward; never overwrite it.
        statement = statement.on_conflict_do_update(
            index_elements=["employee_id", "leave_type_id", "leave_year_id"],
            set_={
                "carried_forward": LeaveBalance.__table__.c.carried_forward
                + statement.excluded.carried_forward
            },
        )
        await session.execute(statement)

    was_active = bool(year.is_active)
    await session.execute(
        update(LeaveYear)
        .where(LeaveYear.id == year.id)
        .values(is_closed=True, closed_at=now, closed_by_id=actor.id)
    )
    if was_active:
        # TWO statements, in this order. A single multi-row UPDATE cannot
        # guarantee which row PostgreSQL touches first, so it can briefly hold
        # two active rows and violate the "only one active year" index — the
        # audit test caught exactly that. Clearing first leaves a moment with no
        # active year, which nothing forbids.
        await session.execute(
            update(LeaveYear)
            .where(LeaveYear.is_active.is_(True))
            .values(is_active=False)
        )
        await session.execute(
            update(LeaveYear)
            .where(LeaveYear.id == next_year.id)
            .values(is_active=True)
        )

    rows_carried = sum(1 for row in log_rows if row["carried_days"] > 0)
    rows_forfeited_only = sum(1 for row in log_rows if row["carried_days"] == 0)

    # ONE audit row for the whole closing (the per-employee detail already lives
    # in leave_carry_forward, so repeating it here would be a second copy).
    await record(
        session,
        actor.id,
        "leave_year",
        year.id,
        "CLOSE",
        old={"is_closed": False},
        new={
            "is_closed": True,
            "from_leave_year": year.name,
            "to_leave_year": next_year.name,
            "to_leave_year_id": next_year.id,
            "log_rows": len(log_rows),
            "rows_carried": rows_carried,
            "rows_forfeited_only": rows_forfeited_only,
            "total_carried": plan["fingerprint"]["total_carried"],
            "total_forfeited": plan["fingerprint"]["total_forfeited"],
            "balances_created": created,
            "balances_updated": updated,
            "skipped_inactive": plan["skipped_inactive"],
            "active_year_moved_to": next_year.name if was_active else None,
            "source": "year-end closing",
        },
    )

    await session.commit()

    active_year = await session.scalar(
        select(LeaveYear).where(LeaveYear.is_active.is_(True))
    )
    return {
        "leave_year_id": year.id,
        "leave_year_name": year.name,
        "next_leave_year_id": next_year.id,
        "next_leave_year_name": next_year.name,
        "rows_carried": rows_carried,
        "rows_forfeited_only": rows_forfeited_only,
        "total_carried": str(_days(plan["fingerprint"]["total_carried"])),
        "total_forfeited": str(_days(plan["fingerprint"]["total_forfeited"])),
        "skipped_inactive": plan["skipped_inactive"],
        "balances_created": created,
        "balances_updated": updated,
        "active_year_id": active_year.id if active_year else None,
        "active_year_name": active_year.name if active_year else None,
        "fingerprint": plan["fingerprint"],
    }


async def reconcile_carry_forward(
    session: AsyncSession, from_year_id: int
) -> list[dict]:
    """READ-ONLY invariant check for one closed year. Empty list = consistent."""
    from app.services.approvals import reconcile_balances

    mismatches: list[dict] = []

    logs = (
        await session.scalars(
            select(LeaveCarryForward).where(
                LeaveCarryForward.from_leave_year_id == from_year_id
            )
        )
    ).all()

    carried_by_key: dict[tuple[int, int], Decimal] = {}
    to_year_ids: set[int] = set()
    employees: set[int] = set()
    for row in logs:
        to_year_ids.add(row.to_leave_year_id)
        employees.add(row.employee_id)
        if _days(row.remaining_at_close) != _days(row.carried_days) + _days(
            row.forfeited_days
        ):
            mismatches.append(
                {
                    "kind": "log_split",
                    "log_id": row.id,
                    "detail": "remaining_at_close != carried + forfeited",
                }
            )
        key = (row.employee_id, row.leave_type_id, row.to_leave_year_id)
        carried_by_key[key] = carried_by_key.get(key, Decimal("0.00")) + _days(
            row.carried_days
        )

    # A manual CARRIED_FORWARD adjustment also belongs in the to-year total.
    carried_adjustments: dict[tuple[int, int, int], Decimal] = {}
    if to_year_ids:
        for row in (
            await session.scalars(
                select(LeaveBalanceAdjustment).where(
                    LeaveBalanceAdjustment.leave_year_id.in_(to_year_ids),
                    LeaveBalanceAdjustment.field
                    == AdjustmentField.CARRIED_FORWARD.value,
                )
            )
        ).all():
            key = (row.employee_id, row.leave_type_id, row.leave_year_id)
            carried_adjustments[key] = carried_adjustments.get(
                key, Decimal("0.00")
            ) + _days(row.delta)

    if to_year_ids:
        balances = (
            await session.scalars(
                select(LeaveBalance).where(
                    LeaveBalance.leave_year_id.in_(to_year_ids)
                )
            )
        ).all()
        seen: dict[tuple[int, int, int], LeaveBalance] = {}
        for balance in balances:
            key = (balance.employee_id, balance.leave_type_id, balance.leave_year_id)
            seen[key] = balance
            if _days(balance.allocated + balance.carried_forward - balance.used - balance.pending) < 0:
                mismatches.append(
                    {
                        "kind": "negative_available",
                        "employee_id": balance.employee_id,
                        "leave_type_id": balance.leave_type_id,
                        "leave_year_id": balance.leave_year_id,
                    }
                )
        for key, want in carried_by_key.items():
            if want == 0:
                # A forfeit-only row carries nothing, so no balance row exists.
                continue
            balance = seen.get(key)
            if balance is None:
                mismatches.append(
                    {
                        "kind": "missing_balance",
                        "employee_id": key[0],
                        "leave_type_id": key[1],
                        "leave_year_id": key[2],
                        "expected_carried": str(want),
                    }
                )
            elif _days(balance.carried_forward) != want + carried_adjustments.get(
                key, Decimal("0.00")
            ):
                mismatches.append(
                    {
                        "kind": "carried_mismatch",
                        "employee_id": key[0],
                        "leave_type_id": key[1],
                        "leave_year_id": key[2],
                        "expected": str(
                            want + carried_adjustments.get(key, Decimal("0.00"))
                        ),
                        "actual": str(_days(balance.carried_forward)),
                    }
                )

    for employee_id in employees:
        for problem in await reconcile_balances(session, employee_id):
            mismatches.append({"kind": "balances", "employee_id": employee_id, **problem})

    return mismatches
