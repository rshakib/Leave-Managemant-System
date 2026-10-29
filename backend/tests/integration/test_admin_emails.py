"""Integration checks for the email preview and the manual queue run (D-195).

These need a throw-away database — the guard in `conftest.py` refuses anything
else — so they are excluded from `pytest -q` by the `integration` marker:

    alembic upgrade head
    pytest -m integration -q tests/integration/test_admin_emails.py

They deliberately do NOT need an administrator's password: the outbox row is
created through the ORM and the router FUNCTIONS are called with a real session.
The HTTP layer (routing + the ADMIN-only dependency) is covered by the live
checks in the phase notes.
"""

import asyncio
import datetime
import uuid

import pytest
from sqlalchemy import delete, select

from app.db.session import async_session_factory
from app.models.email_outbox import EmailAttempt, EmailOutbox, EmailStatus
from app.routers.admin_emails import get_email, process_queue

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def loop():
    """ONE event loop for this module.

    The application's async engine keeps pooled connections that belong to the
    loop that created them, so giving each test its own `asyncio.run()` makes the
    second test fail with "Event loop is closed". pytest-asyncio is not installed
    (the default suite is deliberately plugin-free), so we own the loop here.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()

PAYLOAD = {
    "request_id": 9001,
    "employee_name": "ZZ Preview Tester",
    "employee_code": "ZZ-PREVIEW",
    "leave_type_code": "AL",
    "leave_type_name": "Annual Leave",
    "start_date": "2026-11-02",
    "end_date": "2026-11-04",
    "chargeable_days": "3",
    "reason": "integration check",
    "approver_names": ["ZZ Approver"],
    "balances": [{"leave_type_code": "AL", "available": "17"}],
}


def _new_row() -> EmailOutbox:
    return EmailOutbox(
        event_type="SUBMITTED",
        to_emails=["zz.preview@demo.example.com"],
        cc_emails=[],
        payload=PAYLOAD,
        status=EmailStatus.PENDING,
        attempts=0,
        max_attempts=5,
        next_attempt_at=datetime.datetime.now(datetime.timezone.utc),
        dedupe_key=f"zz-preview-{uuid.uuid4().hex}",
    )


def test_the_detail_endpoint_returns_the_rendered_email(loop):
    async def scenario():
        async with async_session_factory() as session:
            row = _new_row()
            session.add(row)
            await session.commit()
            await session.refresh(row)
            try:
                detail = await get_email(row.id, session)
                # 1. the three rendered fields the admin screen shows
                assert detail.subject and "ZZ Preview Tester" in detail.subject
                assert detail.body_text and "ZZ Preview Tester" in detail.body_text
                assert detail.body_html and "<" in detail.body_html
                # the link points at the frontend request, not at the API
                assert "leave-requests/9001" in detail.body_text
                # the stored facts and the history are still there
                assert detail.payload["request_id"] == 9001
                assert detail.attempt_history == []
                assert detail.status == EmailStatus.PENDING
            finally:
                await session.execute(
                    delete(EmailAttempt).where(EmailAttempt.outbox_id == row.id)
                )
                await session.execute(delete(EmailOutbox).where(EmailOutbox.id == row.id))
                await session.commit()

    loop.run_until_complete(scenario())


def test_process_queue_sends_pending_rows_with_the_console_backend(loop):
    async def scenario():
        async with async_session_factory() as session:
            row = _new_row()
            session.add(row)
            await session.commit()
            await session.refresh(row)
            try:
                due = await session.scalar(
                    select(EmailOutbox).where(EmailOutbox.id == row.id)
                )
                assert due.status == EmailStatus.PENDING

                result = await process_queue(reminders=False, session=session)

                # 2. the manual run really drains the queue
                assert result.sent >= 1
                assert result.processed >= 1
                await session.refresh(row)
                assert row.status == EmailStatus.SENT
                assert row.sent_at is not None
                # and it logged the attempt
                attempts = (
                    await session.scalars(
                        select(EmailAttempt).where(EmailAttempt.outbox_id == row.id)
                    )
                ).all()
                assert attempts and attempts[-1].success is True
                assert attempts[-1].backend == "console"
            finally:
                await session.execute(
                    delete(EmailAttempt).where(EmailAttempt.outbox_id == row.id)
                )
                await session.execute(delete(EmailOutbox).where(EmailOutbox.id == row.id))
                await session.commit()

    loop.run_until_complete(scenario())
