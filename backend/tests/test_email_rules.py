"""Tests for the pure email planning rules (FR-NOT-1/2)."""

from datetime import date

import pytest

from app.services.email_rules import (
    APPROVED,
    APPROVER_ACTED,
    CANCELLED,
    CANCELLED_EMPLOYEE,
    REMINDER,
    REJECTED,
    SUBMITTED,
    backoff_seconds,
    is_overdue,
    next_state_after_failure,
    plan_emails,
    sanitize_header,
    working_days_waiting,
)

FRIDAY, SATURDAY = 5, 6


def facts(**overrides):
    data = {
        "request_id": 7,
        "employee_name": "Alice Example",
        "employee_email": "alice@example.invalid",
        "leave_type_code": "AL",
        "leave_type_name": "Annual Leave",
        "start_date": "2026-11-02",
        "end_date": "2026-11-03",
        "day_type": "FULL_DAY",
        "chargeable_days": "2.00",
        "reason": "family trip",
        "approvers": [
            {
                "id": 2,
                "name": "Bob",
                "email": "bob@example.invalid",
                "status": "PENDING",
                "is_active": True,
            },
            {
                "id": 3,
                "name": "Cara",
                "email": "cara@example.invalid",
                "status": "PENDING",
                "is_active": True,
            },
        ],
        "actor_email": "bob@example.invalid",
        "actor_name": "Bob",
        "approval_id": 11,
        "comment": "ok",
        "balances": [{"leave_year_name": "2026", "available": "18.00"}],
        "notify_cc_admin_emails": ["hr@example.invalid"],
        "notify_cc_admins_on_final": False,
        "cancelled_by_admin": False,
        "cancelled_by_name": "Alice Example",
        "cancel_reason": None,
        "approver_id": 2,
        "approver_name": "Bob",
        "approver_email": "bob@example.invalid",
        "local_date": "2026-11-05",
        "overdue": [],
    }
    data.update(overrides)
    return data


# --- recipients ------------------------------------------------------------


def test_submitted_goes_to_approvers_and_ccs_the_employee():
    spec = plan_emails(SUBMITTED, facts())[0]
    assert spec.to_emails == ("bob@example.invalid", "cara@example.invalid")
    assert spec.cc_emails == ("alice@example.invalid",)


def test_inactive_or_missing_addresses_are_dropped():
    spec = plan_emails(
        SUBMITTED,
        facts(
            approvers=[
                {"name": "Gone", "email": "gone@example.invalid", "is_active": False},
                {"name": "NoMail", "email": None, "is_active": True},
                {"name": "Bob", "email": "bob@example.invalid", "is_active": True},
            ]
        ),
    )[0]
    assert spec.to_emails == ("bob@example.invalid",)


def test_duplicate_addresses_are_removed_and_case_is_ignored():
    spec = plan_emails(
        SUBMITTED,
        facts(
            employee_email="BOB@example.invalid",
            approvers=[
                {"name": "Bob", "email": "bob@example.invalid", "is_active": True},
                {"name": "Bob again", "email": "Bob@Example.Invalid", "is_active": True},
            ],
        ),
    )[0]
    assert spec.to_emails == ("bob@example.invalid",)
    assert spec.cc_emails == ()  # never both To and Cc


def test_approver_acted_tells_the_employee_and_not_the_actor():
    # The facts describe the state AFTER this approval: Bob is now APPROVED.
    updated = [
        {"id": 2, "name": "Bob", "email": "bob@example.invalid",
         "status": "APPROVED", "is_active": True},
        {"id": 3, "name": "Cara", "email": "cara@example.invalid",
         "status": "PENDING", "is_active": True},
    ]
    spec = plan_emails(APPROVER_ACTED, facts(approvers=updated))[0]
    assert spec.to_emails == ("alice@example.invalid",)
    assert spec.cc_emails == ()
    assert spec.payload["actor_name"] == "Bob"
    assert spec.payload["pending_names"] == ["Cara"]


def test_approved_ccs_every_approver_and_excludes_the_actor():
    spec = plan_emails(APPROVED, facts())[0]
    assert spec.to_emails == ("alice@example.invalid",)
    assert spec.cc_emails == ("cara@example.invalid",)  # bob (the actor) is skipped
    assert spec.payload["balances"] == [{"leave_year_name": "2026", "available": "18.00"}]


def test_approved_adds_admin_cc_only_when_enabled():
    off = plan_emails(APPROVED, facts())[0]
    on = plan_emails(APPROVED, facts(notify_cc_admins_on_final=True))[0]
    assert "hr@example.invalid" not in off.cc_emails
    assert "hr@example.invalid" in on.cc_emails


def test_rejected_ccs_the_approvers_and_carries_the_comment():
    spec = plan_emails(REJECTED, facts(actor_name="Cara"))[0]
    assert spec.to_emails == ("alice@example.invalid",)
    assert spec.payload["actor_name"] == "Cara"
    assert spec.payload["comment"] == "ok"


def test_cancelled_by_the_employee_goes_to_the_approvers_only():
    specs = plan_emails(CANCELLED, facts(cancelled_by_admin=False))
    assert len(specs) == 1
    assert specs[0].to_emails == ("bob@example.invalid", "cara@example.invalid")


def test_admin_cancel_also_emails_the_employee():
    specs = plan_emails(
        CANCELLED,
        facts(cancelled_by_admin=True, cancelled_by_name="HR Admin", cancel_reason="shutdown"),
    )
    assert [spec.event_type for spec in specs] == [CANCELLED, CANCELLED_EMPLOYEE]
    employee_mail = specs[1]
    assert employee_mail.to_emails == ("alice@example.invalid",)
    assert employee_mail.payload["cancel_reason"] == "shutdown"


def test_reminder_goes_to_one_approver():
    spec = plan_emails(
        REMINDER,
        facts(overdue=[{"employee_name": "Alice", "waiting": 3}]),
    )[0]
    assert spec.to_emails == ("bob@example.invalid",)


# --- dedupe keys -----------------------------------------------------------


def test_dedupe_keys_are_stable_and_unique_per_event():
    assert plan_emails(SUBMITTED, facts())[0].dedupe_key == "submitted:7"
    assert plan_emails(APPROVER_ACTED, facts())[0].dedupe_key == "approver_acted:7:11"
    assert plan_emails(APPROVED, facts())[0].dedupe_key == "approved:7"
    assert plan_emails(REJECTED, facts())[0].dedupe_key == "rejected:7"
    assert plan_emails(CANCELLED, facts())[0].dedupe_key == "cancelled:7"
    assert plan_emails(REMINDER, facts())[0].dedupe_key == "reminder:2:2026-11-05"
    admin_cancel = plan_emails(CANCELLED, facts(cancelled_by_admin=True))
    assert admin_cancel[1].dedupe_key == "cancelled_employee:7"


def test_unknown_event_raises():
    with pytest.raises(ValueError):
        plan_emails("NOPE", facts())


# --- working days waiting --------------------------------------------------

# 2026-10-26 is a Monday.
MON = date(2026, 10, 26)
TUE = date(2026, 10, 27)
WED = date(2026, 10, 28)
THU = date(2026, 10, 29)
FRI = date(2026, 10, 30)
SAT = date(2026, 10, 31)
SUN = date(2026, 11, 1)
NEXT_TUE = date(2026, 11, 3)

SAT_SUN = {0, 6}
FRI_SAT = {FRIDAY, SATURDAY}


def test_waiting_counts_working_days_after_submission():
    assert working_days_waiting(MON, THU, SAT_SUN, set()) == 3  # Tue, Wed, Thu
    assert working_days_waiting(MON, MON, SAT_SUN, set()) == 0  # same day


def test_waiting_with_a_friday_saturday_weekend():
    # Mon..Fri with Fri+Sat off: only Tue, Wed, Thu count.
    assert working_days_waiting(MON, FRI, FRI_SAT, set()) == 3


def test_waiting_skips_holidays():
    assert working_days_waiting(MON, THU, SAT_SUN, {WED}) == 2


def test_waiting_when_submitted_on_a_weekend():
    # Sat -> next Tuesday: Sun is weekend, Mon + Tue count.
    assert working_days_waiting(SAT, NEXT_TUE, SAT_SUN, set()) == 2


def test_overdue_boundary_is_strictly_greater_than_two():
    two = working_days_waiting(MON, WED, SAT_SUN, set())
    three = working_days_waiting(MON, THU, SAT_SUN, set())
    assert two == 2 and not is_overdue(MON, WED, SAT_SUN, set())
    assert three == 3 and is_overdue(MON, THU, SAT_SUN, set())


# --- retry schedule --------------------------------------------------------


def test_backoff_schedule():
    assert [backoff_seconds(n) for n in range(1, 7)] == [60, 300, 1800, 7200, 43200, 43200]


def test_retry_or_failed():
    assert next_state_after_failure(1, 5) == "RETRY"
    assert next_state_after_failure(4, 5) == "RETRY"
    assert next_state_after_failure(5, 5) == "FAILED"


# --- header safety ---------------------------------------------------------


def test_sanitize_header_strips_newlines_and_control_characters():
    assert sanitize_header("Hello\r\nBcc: evil@example.invalid") == "Hello Bcc: evil@example.invalid"
    assert "\r" not in sanitize_header("a\rb") and "\n" not in sanitize_header("a\nb")
    assert sanitize_header("  lots   of\tspace  ") == "lots of space"
    assert len(sanitize_header("x" * 500)) == 200
