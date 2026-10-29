"""The outbox worker: sends queued emails and enqueues reminder digests.

Run it with:

    python -m app.worker            # forever
    python -m app.worker --once     # one pass (used by tests)

Why `SELECT ... FOR UPDATE SKIP LOCKED`? Each worker locks the rows it is about
to send and *skips* rows another worker already locked. Two workers therefore
never grab the same email, and neither has to wait for the other.
"""

import argparse
import asyncio
import datetime
import logging
import time
import zoneinfo

from sqlalchemy import func, select, update

from app.core.config import settings
from app.db.session import async_session_factory
from app.models.email_outbox import EmailAttempt, EmailOutbox, EmailStatus
from app.models.employee import Employee
from app.models.holiday import Holiday, HolidayType
from app.models.leave_request import (
    ApprovalStatus,
    LeaveRequest,
    LeaveRequestApproval,
    RequestStatus,
)
from app.models.leave_type import LeaveType
from app.models.weekend_setting import WeekendSetting
from app.services.email_rules import (
    backoff_seconds,
    is_overdue,
    next_state_after_failure,
    working_days_waiting,
)
from app.services.email_templates import render_email
from app.services.mailer import Message, send, validate_config
from app.services.maintenance import (
    cleanup,
    release_cleanup_lock,
    try_cleanup_lock,
)
from app.services.notifications import enqueue_events

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("worker")

# NOTE: this worker is a SYSTEM actor — it sends emails and queues reminders, so
# it writes NO audit rows. The audit trail records what PEOPLE did; a delivery
# retry is visible in email_attempt instead (DECISIONS D-148).

BATCH_SIZE = 10
IDLE_SECONDS = 5
STUCK_AFTER = datetime.timedelta(minutes=10)
REMINDER_EVERY_SECONDS = 15 * 60
CLEANUP_EVERY_SECONDS = 24 * 60 * 60
SUBTRACTED_TYPES = (HolidayType.PUBLIC, HolidayType.COMPANY)


# --- sending ---------------------------------------------------------------


async def _claim_batch() -> list[dict]:
    """Lock up to BATCH_SIZE due rows, mark them SENDING, return plain snapshots."""
    async with async_session_factory() as session:
        rows = (
            await session.scalars(
                select(EmailOutbox)
                .where(
                    EmailOutbox.status == EmailStatus.PENDING,
                    EmailOutbox.next_attempt_at <= func.now(),
                )
                .order_by(EmailOutbox.next_attempt_at, EmailOutbox.id)
                .limit(BATCH_SIZE)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if not rows:
            return []

        now = datetime.datetime.now(datetime.timezone.utc)
        snapshots = [
            {
                "id": row.id,
                "event_type": row.event_type,
                "to": list(row.to_emails or []),
                "cc": list(row.cc_emails or []),
                "payload": dict(row.payload or {}),
                "attempts": row.attempts,
                "max_attempts": row.max_attempts,
            }
            for row in rows
        ]
        for row in rows:
            row.status = EmailStatus.SENDING
            row.claimed_at = now
        await session.commit()
        return snapshots


async def _mark_sent(outbox_id: int, backend: str) -> None:
    async with async_session_factory() as session:
        row = await session.get(EmailOutbox, outbox_id)
        if row is None:
            return
        row.status = EmailStatus.SENT
        row.sent_at = datetime.datetime.now(datetime.timezone.utc)
        row.last_error = None
        session.add(
            EmailAttempt(outbox_id=outbox_id, success=True, backend=backend)
        )
        await session.commit()


async def _mark_failed(
    outbox_id: int, error: str, attempts: int, max_attempts: int, backend: str
) -> None:
    async with async_session_factory() as session:
        row = await session.get(EmailOutbox, outbox_id)
        if row is None:
            return
        new_attempts = attempts + 1
        row.attempts = new_attempts
        row.last_error = (error or "unknown error")[:500]
        if next_state_after_failure(new_attempts, max_attempts) == "RETRY":
            row.status = EmailStatus.PENDING
            row.next_attempt_at = datetime.datetime.now(
                datetime.timezone.utc
            ) + datetime.timedelta(seconds=backoff_seconds(new_attempts))
        else:
            row.status = EmailStatus.FAILED
        row.claimed_at = None
        session.add(
            EmailAttempt(
                outbox_id=outbox_id,
                success=False,
                error=(error or "unknown error")[:500],
                backend=backend,
            )
        )
        await session.commit()


async def _deliver(item: dict) -> None:
    """Render and send ONE row. A failure here never stops the worker."""
    backend = settings.email_backend.lower()
    try:
        subject, text, html = render_email(
            item["event_type"], item["payload"], settings.frontend_base_url
        )
        used = send(
            Message(
                to=item["to"], cc=item["cc"], subject=subject, text=text, html=html
            )
        )
        await _mark_sent(item["id"], used)
        logger.info("sent outbox #%s (%s)", item["id"], item["event_type"])
    except Exception as exc:  # noqa: BLE001 - a bad row only fails itself
        logger.warning("outbox #%s failed: %s", item["id"], type(exc).__name__)
        await _mark_failed(
            item["id"], str(exc), item["attempts"], item["max_attempts"], backend
        )


async def drain_once() -> int:
    batch = await _claim_batch()
    for item in batch:
        await _deliver(item)
    return len(batch)


async def recover_stuck() -> int:
    """Rows left in SENDING by a crashed worker go back to PENDING."""
    cutoff = datetime.datetime.now(datetime.timezone.utc) - STUCK_AFTER
    async with async_session_factory() as session:
        result = await session.execute(
            update(EmailOutbox)
            .where(
                EmailOutbox.status == EmailStatus.SENDING,
                EmailOutbox.claimed_at < cutoff,
            )
            .values(status=EmailStatus.PENDING, claimed_at=None)
        )
        await session.commit()
        return result.rowcount or 0


# --- reminders -------------------------------------------------------------


def _weekend_for(employee_id: int, overrides: dict, global_days) -> set[int]:
    if employee_id in overrides:
        return set(overrides[employee_id])
    return set(global_days or [])


def _holiday_applies(holiday: Holiday, employee: Employee) -> bool:
    division_ok = (
        holiday.division_id is None or holiday.division_id == employee.division_id
    )
    department_ok = (
        holiday.department_id is None
        or holiday.department_id == employee.department_id
    )
    return division_ok and department_ok


async def reminder_tick() -> int:
    """Enqueue ONE digest per overdue approver per local date."""
    today = datetime.datetime.now(zoneinfo.ZoneInfo(settings.org_timezone)).date()
    queued = 0

    async with async_session_factory() as session:
        pairs = (
            await session.execute(
                select(LeaveRequestApproval, LeaveRequest)
                .join(
                    LeaveRequest,
                    LeaveRequest.id == LeaveRequestApproval.leave_request_id,
                )
                .where(
                    LeaveRequestApproval.status == ApprovalStatus.PENDING,
                    LeaveRequest.status == RequestStatus.PENDING,
                )
            )
        ).all()
        if not pairs:
            return 0

        approver_ids = {approval.approver_id for approval, _ in pairs}
        approvers = {
            person.id: person
            for person in (
                await session.scalars(
                    select(Employee).where(
                        Employee.id.in_(approver_ids), Employee.is_active.is_(True)
                    )
                )
            ).all()
        }

        overrides = {
            row.employee_id: list(row.days_of_week)
            for row in (
                await session.scalars(
                    select(WeekendSetting).where(
                        WeekendSetting.employee_id.in_(list(approvers))
                    )
                )
            ).all()
        }
        global_row = await session.scalar(
            select(WeekendSetting).where(WeekendSetting.employee_id.is_(None))
        )
        global_days = list(global_row.days_of_week) if global_row else []

        earliest = min(
            request.submitted_at.date() for _, request in pairs
        )
        holidays = (
            await session.scalars(
                select(Holiday).where(
                    Holiday.date >= earliest,
                    Holiday.date <= today,
                    Holiday.type.in_(SUBTRACTED_TYPES),
                )
            )
        ).all()

        employee_ids = {request.employee_id for _, request in pairs}
        askers = {
            person.id: person
            for person in (
                await session.scalars(
                    select(Employee).where(Employee.id.in_(employee_ids))
                )
            ).all()
        }
        types = {
            leave_type.id: leave_type
            for leave_type in (
                await session.scalars(
                    select(LeaveType).where(
                        LeaveType.id.in_({request.leave_type_id for _, request in pairs})
                    )
                )
            ).all()
        }

        for approver_id, approver in approvers.items():
            weekend = _weekend_for(approver_id, overrides, global_days)
            mine = [request for approval, request in pairs if approval.approver_id == approver_id]
            overdue = []
            for request in mine:
                holiday_dates = {
                    holiday.date
                    for holiday in holidays
                    if _holiday_applies(holiday, askers[request.employee_id])
                }
                waiting = working_days_waiting(
                    request.submitted_at.date(), today, weekend, holiday_dates
                )
                if not is_overdue(
                    request.submitted_at.date(),
                    today,
                    weekend,
                    holiday_dates,
                    settings.reminder_after_working_days,
                ):
                    continue
                asker = askers[request.employee_id]
                overdue.append(
                    {
                        "request_id": request.id,
                        "employee_name": asker.full_name,
                        "leave_type_code": types[request.leave_type_id].code,
                        "start_date": str(request.start_date),
                        "end_date": str(request.end_date),
                        "days": str(request.chargeable_days),
                        "waiting": waiting,
                    }
                )
            if not overdue:
                continue
            ignored = await enqueue_events(
                session,
                "REMINDER",
                {
                    "request_id": overdue[0]["request_id"],
                    "approver_id": approver_id,
                    "approver_name": approver.full_name,
                    "approver_email": approver.email,
                    "local_date": str(today),
                    "overdue": overdue,
                },
            )
            queued += ignored
        await session.commit()

    if queued:
        logger.info("reminder tick queued %s digest(s)", queued)
    return queued


async def cleanup_tick():
    """Prune old telemetry/emails ONCE per day.

    An ADVISORY LOCK is a lock the DATABASE holds for us by name: the first
    worker calls `pg_try_advisory_lock(key)` and gets `true`; any other worker
    asking for the same key gets `false`, so only one of them runs the cleanup.
    Nothing is written to a table to remember this — the lock disappears by
    itself when the session ends, which is exactly what we want.
    """
    if not await try_cleanup_lock():
        logger.info("cleanup: another worker is already doing it")
        return None
    try:
        counts = await cleanup(dry_run=False)
    finally:
        await release_cleanup_lock()
    logger.info("cleanup pruned: %s", counts)
    return counts


# --- loop ------------------------------------------------------------------


async def run(once: bool) -> None:
    validate_config()
    recovered = await recover_stuck()
    if recovered:
        logger.info("recovered %s stuck row(s)", recovered)

    if once:
        queued = await reminder_tick()
        if queued:
            logger.info("reminder tick queued %s digest(s)", queued)
        total = 0
        while True:
            sent = await drain_once()
            total += sent
            if sent == 0:
                break
        logger.info("--once finished, processed %s row(s)", total)
        return

    last_reminder = 0.0
    last_cleanup = 0.0
    while True:
        now = time.monotonic()
        if now - last_cleanup >= CLEANUP_EVERY_SECONDS:
            last_cleanup = now
            try:
                await cleanup_tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning("cleanup tick failed: %s", type(exc).__name__)

        if now - last_reminder >= REMINDER_EVERY_SECONDS:
            last_reminder = now
            try:
                await reminder_tick()
            except Exception as exc:  # noqa: BLE001
                logger.warning("reminder tick failed: %s", type(exc).__name__)

        try:
            await recover_stuck()
            worked = await drain_once()
        except Exception as exc:  # noqa: BLE001
            logger.warning("drain failed: %s", type(exc).__name__)
            worked = 0
        if worked == 0:
            await asyncio.sleep(IDLE_SECONDS)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the email outbox worker.")
    parser.add_argument(
        "--once", action="store_true", help="process everything due, then exit"
    )
    args = parser.parse_args()
    try:
        asyncio.run(run(args.once))
    except KeyboardInterrupt:
        logger.info("worker stopped")


if __name__ == "__main__":
    main()
