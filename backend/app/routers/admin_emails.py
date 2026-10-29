import datetime
import zoneinfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import func

from app.core.config import settings
from app.core.deps import require_roles
from app.db.session import get_session
from app.models.email_outbox import (
    EmailAttempt,
    EmailAttemptRead,
    EmailOutbox,
    EmailOutboxDetail,
    EmailOutboxRead,
    EmailStatus,
    QueueRunResult,
)
from app.models.employee import Role
from app.services.email_templates import render_preview
from app.worker import drain_once, recover_stuck, reminder_tick

router = APIRouter(prefix="/admin/emails", tags=["admin-emails"])

ADMIN_ONLY = [Depends(require_roles(Role.ADMIN))]


def _day_bounds(
    date_from: datetime.date | None, date_to: datetime.date | None
) -> tuple[datetime.datetime | None, datetime.datetime | None]:
    tz = zoneinfo.ZoneInfo(settings.org_timezone)
    start = (
        datetime.datetime.combine(date_from, datetime.time.min, tzinfo=tz)
        if date_from
        else None
    )
    end = (
        datetime.datetime.combine(
            date_to + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz
        )
        if date_to
        else None
    )
    return start, end


@router.get("", response_model=list[EmailOutboxRead], dependencies=ADMIN_ONLY)
async def list_emails(
    status_filter: EmailStatus | None = Query(default=None, alias="status"),
    event_type: str | None = None,
    related_request_id: int | None = None,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> list[EmailOutboxRead]:
    statement = select(EmailOutbox)
    if status_filter is not None:
        statement = statement.where(EmailOutbox.status == status_filter)
    if event_type is not None:
        statement = statement.where(EmailOutbox.event_type == event_type)
    if related_request_id is not None:
        statement = statement.where(
            EmailOutbox.related_request_id == related_request_id
        )
    start, end = _day_bounds(date_from, date_to)
    if start is not None:
        statement = statement.where(EmailOutbox.created_at >= start)
    if end is not None:
        statement = statement.where(EmailOutbox.created_at < end)
    statement = (
        statement.order_by(EmailOutbox.created_at.desc(), EmailOutbox.id.desc())
        .offset(max(0, offset))
        .limit(min(max(1, limit), 100))
    )
    rows = (await session.scalars(statement)).all()
    return [EmailOutboxRead.model_validate(row) for row in rows]


@router.get("/{email_id}", response_model=EmailOutboxDetail, dependencies=ADMIN_ONLY)
async def get_email(
    email_id: int,
    session: AsyncSession = Depends(get_session),
) -> EmailOutboxDetail:
    row = await session.get(EmailOutbox, email_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found.")
    attempts = (
        await session.scalars(
            select(EmailAttempt)
            .where(EmailAttempt.outbox_id == email_id)
            .order_by(EmailAttempt.id)
        )
    ).all()
    payload = dict(row.payload or {})
    subject, body_text, body_html = render_preview(
        str(row.event_type), payload, settings.frontend_base_url
    )
    return EmailOutboxDetail(
        **EmailOutboxRead.model_validate(row).model_dump(),
        payload=payload,
        attempt_history=[EmailAttemptRead.model_validate(a) for a in attempts],
        subject=subject,
        body_text=body_text,
        body_html=body_html,
    )


async def _status_counts(session: AsyncSession) -> dict[str, int]:
    rows = await session.execute(
        select(EmailOutbox.status, func.count()).group_by(EmailOutbox.status)
    )
    return {str(name): count for name, count in rows.all()}


@router.post("/process-queue", response_model=QueueRunResult, dependencies=ADMIN_ONLY)
async def process_queue(
    reminders: bool = False,
    session: AsyncSession = Depends(get_session),
) -> QueueRunResult:
    """Run ONE pass of the email worker right now.

    The screen calls this so a demo never has to wait for the background worker —
    or open a second terminal. It runs exactly the same code the worker runs
    (`worker.drain_once()` / `worker.reminder_tick()`), and it is a system action,
    so it writes no audit row (D-148/D-195). `?reminders=true` also runs the
    pending-approval reminder tick, then drains what it queued.
    """
    before = await _status_counts(session)
    await session.commit()  # end this transaction so the counts below are fresh

    await recover_stuck()
    processed = await drain_once()

    reminders_queued = 0
    if reminders:
        reminders_queued = await reminder_tick()
        if reminders_queued:
            processed += await drain_once()

    after = await _status_counts(session)
    return QueueRunResult(
        processed=processed,
        sent=after.get("SENT", 0) - before.get("SENT", 0),
        failed=after.get("FAILED", 0) - before.get("FAILED", 0),
        still_pending=after.get("PENDING", 0) + after.get("SENDING", 0),
        reminders_queued=reminders_queued,
    )


@router.post("/{email_id}/retry", response_model=EmailOutboxRead, dependencies=ADMIN_ONLY)
async def retry_email(
    email_id: int,
    session: AsyncSession = Depends(get_session),
) -> EmailOutboxRead:
    """Only a FAILED email can be retried; the old attempts stay in the log."""
    row = await session.get(EmailOutbox, email_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Email not found.")
    if row.status != EmailStatus.FAILED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Only FAILED emails can be retried (this one is {row.status}).",
        )

    row.status = EmailStatus.PENDING
    row.attempts = 0
    row.claimed_at = None
    row.next_attempt_at = datetime.datetime.now(datetime.timezone.utc)
    await session.commit()
    await session.refresh(row)
    return EmailOutboxRead.model_validate(row)
