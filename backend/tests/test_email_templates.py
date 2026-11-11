"""Tests for the Jinja2 email templates (escaping + links)."""

import pytest

from app.services.email_rules import (
    APPROVED,
    APPROVED_SUPERVISOR,
    APPROVER_ACTED,
    CANCELLED,
    CANCELLED_EMPLOYEE,
    CURTAILMENT_APPROVED,
    CURTAILMENT_REJECTED,
    CURTAILMENT_SUBMITTED,
    PASSWORD_RESET,
    REJECTED,
    REMINDER,
    SUBMITTED,
)
from app.services.email_templates import render_email

BASE = "http://localhost:5173"


def payload(**overrides):
    data = {
        "request_id": 42,
        "employee_code": "EMP-042",
        "employee_name": "Alice Example",
        "supervisor_name": "Bob Supervisor",
        "leave_type_code": "AL",
        "leave_type_name": "Annual Leave",
        "start_date": "2026-11-02",
        "end_date": "2026-11-03",
        "day_type": "FULL_DAY",
        "chargeable_days": "2.00",
        "reason": "family trip",
        "approver_count": 2,
        "actor_name": "Bob",
        "pending_names": ["Cara"],
        "comment": "busy season",
        "balances": [{"leave_year_name": "2026", "available": "18.00"}],
        "cancelled_by_name": "HR Admin",
        "cancel_reason": "company shutdown",
        "approver_name": "Bob",
        "curtailment_id": 99,
        "original_end_date": "2026-11-05",
        "curtailed_end_date": "2026-11-03",
        "curtailed_day_type": "FULL_DAY",
        "days_to_refund": "2.00",
        "new_days": "2.00",
        "original_days": "4.00",
        "decision_note": "Approved early return",
        "curtailment_reason": "Finished task early",
        "overdue": [
            {
                "employee_name": "Alice",
                "leave_type_code": "AL",
                "start_date": "2026-10-26",
                "end_date": "2026-10-27",
                "days": "2.00",
                "waiting": 4,
            }
        ],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "event",
    [
        SUBMITTED,
        APPROVER_ACTED,
        APPROVED,
        APPROVED_SUPERVISOR,
        REJECTED,
        CANCELLED,
        CANCELLED_EMPLOYEE,
        REMINDER,
        PASSWORD_RESET,
        CURTAILMENT_SUBMITTED,
        CURTAILMENT_APPROVED,
        CURTAILMENT_REJECTED,
    ],
)
def test_every_event_renders_a_subject_text_and_html(event):
    data = payload(token="secure_test_token_123")
    subject, text, html = render_email(event, data, BASE)
    assert subject
    assert text.strip()
    assert html.strip()
    assert "\r" not in subject and "\n" not in subject


def test_password_reset_links_to_reset_page():
    data = payload(token="abc-reset-token-xyz")
    subject, text, html = render_email(PASSWORD_RESET, data, BASE)
    assert f"{BASE}/reset-password?token=abc-reset-token-xyz" in text
    assert f"{BASE}/reset-password?token=abc-reset-token-xyz" in html
    assert "password" in subject.lower()


def test_links_never_contain_a_token():
    _, text, html = render_email(SUBMITTED, payload(), BASE)
    assert f"{BASE}/leave-requests/42" in text
    assert f"{BASE}/leave-requests/42" in html
    assert "token" not in text.lower()
    assert "password" not in html.lower()


def test_reminder_links_to_the_approvals_page():
    _, text, _ = render_email(REMINDER, payload(), BASE)
    assert f"{BASE}/approvals" in text


def test_reason_is_escaped_in_the_html():
    _, text, html = render_email(
        SUBMITTED, payload(reason='<script>alert(1)</script>'), BASE
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    # Plain text keeps the raw characters (that is fine: no HTML there).
    assert "<script>alert(1)</script>" in text


def test_a_name_with_a_line_break_cannot_inject_a_header():
    subject, _, _ = render_email(
        APPROVED, payload(employee_name="Alice\r\nBcc: evil@example.invalid"), BASE
    )
    assert "\r" not in subject and "\n" not in subject
    assert "Bcc: evil@example.invalid" in subject  # flattened, not a new header


def test_reason_is_shortened_to_300_characters():
    long_reason = "x" * 500
    _, text, _ = render_email(SUBMITTED, payload(reason=long_reason), BASE)
    assert "x" * 301 not in text
    assert "…" in text


def test_unknown_event_raises():
    with pytest.raises(ValueError):
        render_email("NOPE", payload(), BASE)
