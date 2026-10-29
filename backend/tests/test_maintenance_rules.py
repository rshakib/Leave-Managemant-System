"""Tests for the pure retention + readiness rules."""

import datetime
from types import SimpleNamespace

import pytest

from app.services.maintenance_rules import (
    is_prunable_login_attempt,
    is_prunable_outbox,
    is_prunable_refresh_token,
    readiness_state,
    retention_cutoffs,
)

NOW = datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.timezone.utc)
SETTINGS = SimpleNamespace(
    retention_login_attempt_days=30,
    retention_refresh_token_days=30,
    retention_sent_email_days=90,
)


def ago(**kwargs):
    return NOW - datetime.timedelta(**kwargs)


# --- cutoffs ---------------------------------------------------------------


def test_cutoffs_use_the_configured_days():
    cutoffs = retention_cutoffs(NOW, SETTINGS)
    assert cutoffs["login_attempt"] == ago(days=30)
    assert cutoffs["refresh_token"] == ago(days=30)
    assert cutoffs["email_outbox"] == ago(days=90)


# --- login attempts --------------------------------------------------------


def test_a_login_attempt_just_before_the_cutoff_is_kept():
    assert is_prunable_login_attempt(ago(days=30, seconds=-1), ago(days=30)) is False


def test_exactly_at_the_cutoff_is_kept():
    assert is_prunable_login_attempt(ago(days=30), ago(days=30)) is False


def test_just_after_the_cutoff_is_prunable():
    assert is_prunable_login_attempt(ago(days=30, seconds=1), ago(days=30)) is True


# --- refresh tokens --------------------------------------------------------


CUTOFF = ago(days=30)


def test_an_unexpired_unrevoked_token_is_never_prunable():
    assert (
        is_prunable_refresh_token(NOW + datetime.timedelta(days=3), None, None, CUTOFF)
        is False
    )


def test_an_expired_token_older_than_the_cutoff_is_prunable():
    assert is_prunable_refresh_token(ago(days=40), None, None, CUTOFF) is True


def test_a_recently_revoked_token_is_kept():
    assert is_prunable_refresh_token(NOW, ago(days=1), None, CUTOFF) is False


def test_a_long_revoked_token_is_prunable():
    assert is_prunable_refresh_token(NOW, ago(days=31), None, CUTOFF) is True


def test_a_replaced_token_follows_the_replacement_time():
    assert is_prunable_refresh_token(NOW, ago(days=90), ago(days=2), CUTOFF) is False
    assert is_prunable_refresh_token(NOW, None, ago(days=31), CUTOFF) is True


def test_boundaries_of_the_token_cutoff():
    assert is_prunable_refresh_token(ago(days=30), None, None, CUTOFF) is False
    assert is_prunable_refresh_token(ago(days=30, seconds=1), None, None, CUTOFF) is True


# --- outbox ----------------------------------------------------------------


EMAIL_CUTOFF = ago(days=90)


@pytest.mark.parametrize("status", ["PENDING", "SENDING", "FAILED"])
def test_only_sent_emails_are_prunable(status):
    assert is_prunable_outbox(status, ago(days=400), EMAIL_CUTOFF) is False


def test_an_old_sent_email_is_prunable():
    assert is_prunable_outbox("SENT", ago(days=91), EMAIL_CUTOFF) is True


def test_a_recent_sent_email_is_kept():
    assert is_prunable_outbox("SENT", ago(days=10), EMAIL_CUTOFF) is False


def test_a_sent_email_without_a_timestamp_is_kept():
    assert is_prunable_outbox("SENT", None, EMAIL_CUTOFF) is False


# --- readiness -------------------------------------------------------------


def test_a_healthy_stack_is_ready():
    state = readiness_state(True, "abc", "abc", None, 3600)
    assert state.ok is True and state.reasons == [] and state.warnings == []


def test_database_down_is_unavailable():
    state = readiness_state(False, None, "abc", None, 3600)
    assert state.ok is False
    assert state.reasons == ["database"]


def test_migrations_behind_is_unavailable():
    state = readiness_state(True, "old", "abc", None, 3600)
    assert state.ok is False
    assert state.reasons == ["migrations"]


def test_a_stale_pending_email_only_warns():
    state = readiness_state(True, "abc", "abc", 7200, 3600)
    assert state.ok is True
    assert state.warnings == ["email"]


def test_a_fresh_pending_email_does_not_warn():
    state = readiness_state(True, "abc", "abc", 60, 3600)
    assert state.ok is True and state.warnings == []


def test_the_reasons_are_short_and_never_leak_details():
    state = readiness_state(False, "rev-123", "rev-456", None, 3600)
    assert state.reasons == ["database"]
    assert all(len(reason) < 20 for reason in state.reasons)
