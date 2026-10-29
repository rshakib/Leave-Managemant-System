"""The transactional outbox (DECISIONS D-19).

`enqueue_events` INSERTs rows inside the CALLER's transaction, before its single
commit. It never renders or sends anything — a mail problem can therefore never
roll back a leave action, and the worker does the sending later.
"""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.email_outbox import EmailOutbox, EmailStatus
from app.services.email_rules import plan_emails


async def enqueue_events(
    session: AsyncSession, event, facts: dict
) -> int:
    """Queue the emails for `event`. Idempotent thanks to `dedupe_key`."""
    specs = plan_emails(event, facts)

    rows = [
        {
            "event_type": spec.event_type,
            "to_emails": list(spec.to_emails),
            "cc_emails": list(spec.cc_emails),
            "payload": spec.payload,
            "related_request_id": facts.get("request_id"),
            "status": EmailStatus.PENDING.value,
            "attempts": 0,
            "max_attempts": settings.email_max_attempts,
            "dedupe_key": spec.dedupe_key,
        }
        for spec in specs
        if spec.to_emails  # never queue an email with nobody to send it to
    ]
    if not rows:
        return 0

    statement = (
        pg_insert(EmailOutbox)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    await session.execute(statement)
    return len(rows)


def _text(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


async def balances_after(session: AsyncSession, request) -> list[dict]:
    """The remaining available days per leave year, AFTER the change."""
    from sqlalchemy import select

    from app.models.leave_balance import LeaveBalance
    from app.models.leave_request import LeaveRequestAllocation
    from app.models.leave_year import LeaveYear

    allocations = (
        await session.scalars(
            select(LeaveRequestAllocation)
            .where(LeaveRequestAllocation.leave_request_id == request.id)
            .order_by(LeaveRequestAllocation.leave_year_id)
        )
    ).all()
    if not allocations:
        return []

    year_ids = [row.leave_year_id for row in allocations]
    years = {
        year.id: year
        for year in (
            await session.scalars(select(LeaveYear).where(LeaveYear.id.in_(year_ids)))
        ).all()
    }
    balances = {
        balance.leave_year_id: balance
        for balance in (
            await session.scalars(
                select(LeaveBalance).where(
                    LeaveBalance.employee_id == request.employee_id,
                    LeaveBalance.leave_type_id == request.leave_type_id,
                    LeaveBalance.leave_year_id.in_(year_ids),
                )
            )
        ).all()
    }
    return [
        {
            "leave_year_name": years[year_id].name,
            "available": str(balances[year_id].available),
        }
        for year_id in year_ids
        if year_id in years and year_id in balances
    ]


async def build_facts(
    session: AsyncSession,
    request,
    balances: list[dict] | None = None,
    extra: dict | None = None,
) -> dict:
    """Collect the facts for a request from the CURRENT (in-memory) state.

    Deliberately no `populate_existing`: the caller has just changed the rows in
    this session, and we want those changes, not the old database values.
    """
    from sqlalchemy import select

    from app.models.employee import Employee
    from app.models.leave_request import LeaveRequestApproval
    from app.models.leave_type import LeaveType

    employee = await session.get(Employee, request.employee_id)
    leave_type = await session.get(LeaveType, request.leave_type_id)
    rows = (
        await session.scalars(
            select(LeaveRequestApproval)
            .where(LeaveRequestApproval.leave_request_id == request.id)
            .order_by(LeaveRequestApproval.approver_id)
        )
    ).all()

    approver_ids = {row.approver_id for row in rows}
    people = {}
    if approver_ids:
        people = {
            person.id: person
            for person in (
                await session.scalars(
                    select(Employee).where(Employee.id.in_(approver_ids))
                )
            ).all()
        }

    facts = {
        "request_id": request.id,
        "employee_name": employee.full_name,
        "employee_email": employee.email,
        "leave_type_code": leave_type.code,
        "leave_type_name": leave_type.name,
        "start_date": str(request.start_date),
        "end_date": str(request.end_date),
        "day_type": _text(request.day_type),
        "chargeable_days": str(request.chargeable_days),
        "reason": request.reason,
        "approvers": [
            {
                "id": row.approver_id,
                "name": people[row.approver_id].full_name
                if row.approver_id in people
                else "",
                "email": people[row.approver_id].email
                if row.approver_id in people
                else None,
                "status": _text(row.status),
                "is_active": people[row.approver_id].is_active
                if row.approver_id in people
                else False,
            }
            for row in rows
        ],
        "notify_cc_admin_emails": settings.notify_cc_admin_emails_list,
        "notify_cc_admins_on_final": settings.notify_cc_admins_on_final,
    }
    if balances is not None:
        facts["balances"] = balances
    if extra:
        facts.update(extra)
    return facts
