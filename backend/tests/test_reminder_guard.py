import pytest
from unittest.mock import patch, MagicMock
from app.core.config import settings
from app.worker import reminder_tick, _deliver
from app.services.notifications import enqueue_events

@pytest.mark.anyio
async def test_reminder_tick_returns_zero_when_disabled():
    with patch.object(settings, "enable_approval_reminders", False):
        result = await reminder_tick()
        assert result == 0

@pytest.mark.anyio
async def test_enqueue_events_skips_reminder_when_disabled():
    session = MagicMock()
    with patch.object(settings, "enable_approval_reminders", False):
        queued = await enqueue_events(session, "REMINDER", {"approver_id": 1, "local_date": "2026-11-01"})
        assert queued == 0

@pytest.mark.anyio
async def test_deliver_suppresses_reminder_when_disabled():
    item = {
        "id": 9999,
        "event_type": "REMINDER",
        "to": ["test@example.com"],
        "cc": [],
        "payload": {},
        "attempts": 0,
        "max_attempts": 5,
    }
    with patch.object(settings, "enable_approval_reminders", False):
        with patch("app.worker._mark_sent") as mock_mark_sent:
            await _deliver(item)
            mock_mark_sent.assert_called_once_with(9999, "suppressed")
