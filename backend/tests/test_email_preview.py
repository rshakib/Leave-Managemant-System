"""The email preview renderer used by GET /admin/emails/{id} (D-195)."""

import pytest

from app.services.email_rules import (
    APPROVED,
    APPROVER_ACTED,
    CANCELLED,
    CANCELLED_EMPLOYEE,
    REJECTED,
    REMINDER,
    SUBMITTED,
)
from app.services.email_templates import render_preview

BASE = "https://app.example.com"

PAYLOADS = {
    SUBMITTED: {
        "request_id": 7, "employee_name": "Nusrat Jahan", "employee_code": "DEMO-002",
        "leave_type_code": "AL", "leave_type_name": "Annual Leave",
        "start_date": "2026-11-02", "end_date": "2026-11-04", "chargeable_days": "3",
        "reason": "Family function", "approver_names": ["Rafiqul Islam"],
        "balances": [{"leave_type_code": "AL", "available": "17"}],
    },
    APPROVER_ACTED: {
        "request_id": 7, "employee_name": "Nusrat Jahan", "actor_name": "Rafiqul Islam",
        "remaining_approvers": ["Farhana Akter"], "chargeable_days": "3",
        "start_date": "2026-11-02", "end_date": "2026-11-04",
    },
    APPROVED: {
        "request_id": 7, "employee_name": "Nusrat Jahan", "leave_type_code": "AL",
        "start_date": "2026-11-02", "end_date": "2026-11-04", "chargeable_days": "3",
        "balances": [{"leave_type_code": "AL", "available": "17"}],
    },
    REJECTED: {
        "request_id": 7, "employee_name": "Nusrat Jahan", "approver_name": "Tanvir Ahmed",
        "comment": "Critical maintenance week", "chargeable_days": "3",
        "start_date": "2026-11-02", "end_date": "2026-11-04",
    },
    CANCELLED: {
        "request_id": 7, "employee_name": "Nusrat Jahan", "cancelled_by_name": "Demo Admin",
        "cancel_reason": "wrong dates", "start_date": "2026-11-02",
        "end_date": "2026-11-04", "chargeable_days": "3",
    },
    CANCELLED_EMPLOYEE: {
        "request_id": 7, "employee_name": "Nusrat Jahan", "cancelled_by_name": "Demo Admin",
        "cancel_reason": "wrong dates", "start_date": "2026-11-02",
        "end_date": "2026-11-04", "chargeable_days": "3",
    },
    REMINDER: {
        "approver_name": "Rafiqul Islam", "overdue": [
            {"employee_name": "Nusrat Jahan", "start_date": "2026-11-02",
             "end_date": "2026-11-04", "chargeable_days": "3"},
        ],
    },
}


@pytest.mark.parametrize("event_type", sorted(PAYLOADS))
def test_every_event_renders_a_subject_text_and_html(event_type):
    subject, text, html = render_preview(event_type, PAYLOADS[event_type], BASE)
    assert subject and isinstance(subject, str)
    assert text and len(text) > 20
    assert html and "<" in html and ">" in html
    # The link in the body points at the frontend, never at the API.
    assert "leave-requests/7" in text or "approvals" in text


def test_the_subject_is_a_single_safe_line():
    subject, _text, _html = render_preview(SUBMITTED, PAYLOADS[SUBMITTED], BASE)
    assert "\n" not in subject and "\r" not in subject
    assert "Nusrat Jahan" in subject


def test_the_html_body_escapes_user_text():
    payload = dict(PAYLOADS[SUBMITTED])
    payload["reason"] = "<script>alert(1)</script>"
    _subject, _text, html = render_preview(SUBMITTED, payload, BASE)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_an_unknown_event_type_returns_none_instead_of_raising():
    assert render_preview("NO_SUCH_EVENT", {"request_id": 1}, BASE) == (None, None, None)


def test_a_broken_payload_never_raises():
    for payload in (None, {}, {"request_id": None, "employee_name": None}):
        subject, text, html = render_preview(SUBMITTED, payload, BASE)
        # It either renders something or reports nothing — but never explodes.
        assert all(value is None for value in (subject, text, html)) or subject
