"""Tests for the pure security rules (no database, no network)."""

import datetime
from types import SimpleNamespace

import pytest

from app.services.security_rules import (
    EXPIRED,
    FAMILY_TOO_OLD,
    REUSED_THEFT,
    REUSED_WITHIN_GRACE,
    REVOKED,
    VALID,
    LoginLimits,
    check_password_policy,
    classify_refresh,
    client_ip,
    decide_login,
    hash_ip,
    hash_token,
    new_token,
    validate_production_settings,
)

NOW = datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.timezone.utc)
GRACE = 10
MAX_FAMILY_DAYS = 30


def token_row(**overrides):
    values = {
        "expires_at": NOW + datetime.timedelta(days=7),
        "revoked_at": None,
        "replaced_at": None,
        "family_started_at": NOW - datetime.timedelta(days=1),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


# --- token helpers ---------------------------------------------------------


def test_hash_token_is_deterministic_and_distinct():
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")
    assert len(hash_token("abc")) == 64
    assert hash_token("") == hash_token("")


def test_new_token_is_long_and_random():
    first, second = new_token(), new_token()
    assert first != second
    assert len(first) >= 60


# --- classify_refresh ------------------------------------------------------


def test_a_fresh_token_is_valid():
    assert classify_refresh(token_row(), NOW, GRACE, MAX_FAMILY_DAYS) == VALID


def test_an_expired_token():
    row = token_row(expires_at=NOW)
    assert classify_refresh(row, NOW, GRACE, MAX_FAMILY_DAYS) == EXPIRED


def test_a_family_older_than_the_limit():
    row = token_row(family_started_at=NOW - datetime.timedelta(days=31))
    assert classify_refresh(row, NOW, GRACE, MAX_FAMILY_DAYS) == FAMILY_TOO_OLD


def test_a_revoked_but_not_rotated_token():
    row = token_row(revoked_at=NOW - datetime.timedelta(minutes=5))
    assert classify_refresh(row, NOW, GRACE, MAX_FAMILY_DAYS) == REVOKED


def test_replaced_inside_the_grace_window_is_a_benign_race():
    row = token_row(replaced_at=NOW - datetime.timedelta(seconds=GRACE - 1))
    assert classify_refresh(row, NOW, GRACE, MAX_FAMILY_DAYS) == REUSED_WITHIN_GRACE


def test_replaced_exactly_at_the_grace_boundary_counts_as_theft():
    row = token_row(replaced_at=NOW - datetime.timedelta(seconds=GRACE))
    assert classify_refresh(row, NOW, GRACE, MAX_FAMILY_DAYS) == REUSED_THEFT


def test_replaced_long_ago_is_theft():
    row = token_row(replaced_at=NOW - datetime.timedelta(minutes=30))
    assert classify_refresh(row, NOW, GRACE, MAX_FAMILY_DAYS) == REUSED_THEFT


def test_replaced_wins_over_revoked():
    row = token_row(
        replaced_at=NOW - datetime.timedelta(minutes=30),
        revoked_at=NOW - datetime.timedelta(minutes=31),
    )
    assert classify_refresh(row, NOW, GRACE, MAX_FAMILY_DAYS) == REUSED_THEFT


# --- decide_login ----------------------------------------------------------


LIMITS = LoginLimits()


def failures(count, seconds_ago=30):
    return [NOW - datetime.timedelta(seconds=seconds_ago)] * count


def test_below_every_limit_is_allowed():
    assert decide_login(NOW, failures(4), failures(29), failures(19), LIMITS).allowed


def test_exactly_at_the_pair_limit_blocks():
    decision = decide_login(NOW, failures(5), [], [], LIMITS)
    assert decision.allowed is False
    assert 1 <= decision.retry_after_seconds <= LIMITS.pair_window_seconds


def test_the_ip_limit_blocks_on_its_own():
    assert decide_login(NOW, [], failures(30), [], LIMITS).allowed is False


def test_the_email_limit_blocks_on_its_own():
    assert decide_login(NOW, [], [], failures(20), LIMITS).allowed is False


def test_the_retry_after_shrinks_as_the_window_passes():
    old = [NOW - datetime.timedelta(seconds=890)] * 5
    assert decide_login(NOW, old, [], [], LIMITS).retry_after_seconds == 10


def test_old_failures_stop_counting():
    stale = [NOW - datetime.timedelta(seconds=LIMITS.pair_window_seconds + 1)] * 10
    assert decide_login(NOW, stale, [], [], LIMITS).allowed is True


def test_the_longest_wait_wins():
    decision = decide_login(
        NOW,
        failures(5, 60),
        failures(30, 60),
        failures(20, 3000),
        LIMITS,
    )
    assert decision.allowed is False
    # pair and IP failures are 60 s old -> 840 s left; the email one has 600 s
    assert decision.retry_after_seconds == 840


# --- client_ip -------------------------------------------------------------


def test_without_trusted_proxies_the_header_is_ignored():
    assert client_ip("10.0.0.9", "1.2.3.4", 0) == "10.0.0.9"


def test_a_forged_header_cannot_spoof_the_address():
    assert client_ip("10.0.0.9", "8.8.8.8, 9.9.9.9", 0) == "10.0.0.9"


def test_one_trusted_proxy_takes_the_last_entry():
    assert client_ip("10.0.0.9", "203.0.113.7, 10.0.0.9", 1) == "10.0.0.9"


def test_two_trusted_proxies_take_the_entry_before_it():
    assert (
        client_ip("10.0.0.9", "203.0.113.7, 10.0.0.8, 10.0.0.9", 2) == "10.0.0.8"
    )


def test_an_ipv6_address_survives():
    assert client_ip("2001:db8::1", "", 1) == "2001:db8::1"
    assert client_ip("::1", "2001:db8::2, ::1", 1) == "::1"


def test_a_malformed_or_short_header_falls_back_to_the_peer():
    assert client_ip("10.0.0.9", "  ,  ", 1) == "10.0.0.9"
    assert client_ip("10.0.0.9", "1.2.3.4", 3) == "10.0.0.9"


# --- hash_ip ---------------------------------------------------------------


def test_hash_ip_is_stable_and_keyed():
    assert hash_ip("1.2.3.4", "key") == hash_ip("1.2.3.4", "key")
    assert hash_ip("1.2.3.4", "key") != hash_ip("1.2.3.4", "other")
    assert len(hash_ip("1.2.3.4", "key")) == 64
    assert "1.2.3.4" not in hash_ip("1.2.3.4", "key")


# --- password policy -------------------------------------------------------


def test_a_good_password_has_no_problems():
    assert check_password_policy("Tr0ub4dor&3x", "someone@example.invalid") == []


def test_too_short():
    problems = check_password_policy("short123", None)
    assert any("at least 10" in problem for problem in problems)


def test_too_long():
    problems = check_password_policy("x" * 129, None)
    assert any("at most 128" in problem for problem in problems)


def test_a_common_password():
    problems = check_password_policy("PASSWORD1", None)
    assert any("common" in problem for problem in problems)


def test_a_repeated_character():
    problems = check_password_policy("aaaaaaaaaaaa", None)
    assert any("repeated" in problem for problem in problems)


def test_the_email_local_part_is_refused():
    problems = check_password_policy("shakib12345", "shakib@example.invalid")
    assert any("email name" in problem for problem in problems)


def test_a_short_email_name_is_not_checked():
    assert check_password_policy("bob123456789", "bob@example.invalid") == []


def test_the_policy_is_case_insensitive_about_the_email():
    problems = check_password_policy("SHAKIB12345", "shakib@example.invalid")
    assert any("email name" in problem for problem in problems)


# --- production settings ---------------------------------------------------


SAFE = {
    "app_env": "production",
    "jwt_secret": "z" * 48,
    "cookie_secure": True,
    "cors_origins": "https://app.example.com",
    "enable_docs": False,
    "email_backend": "smtp",
    "trusted_proxy_count": 1,
    "access_token_minutes": 15,
    "ip_hash_key": "k" * 48,
    "storage_backend": "s3",
    "s3_bucket": "lms-attachments",
    "s3_access_key_id": "AKIAEXAMPLE",
    "s3_secret_access_key": "s3-secret-value-not-a-placeholder",
    "s3_region": "eu-central-1",
    "cookie_samesite": "lax",
}


def test_a_safe_production_configuration_passes():
    assert validate_production_settings(SAFE) == []


def test_development_never_reports_problems():
    unsafe = dict(SAFE, app_env="development", jwt_secret="dev", cookie_secure=False)
    assert validate_production_settings(unsafe) == []


@pytest.mark.parametrize(
    ("override", "needle"),
    [
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"jwt_secret": "changeme"}, "JWT_SECRET"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"cors_origins": "http://localhost:5173"}, "CORS_ORIGINS"),
        ({"cors_origins": "http://app.example.com"}, "https"),
        ({"cors_origins": ""}, "CORS_ORIGINS"),
        ({"enable_docs": True}, "ENABLE_DOCS"),
        ({"email_backend": "console"}, "EMAIL_BACKEND"),
        ({"email_backend": "file"}, "EMAIL_BACKEND"),
        ({"trusted_proxy_count": 0}, "TRUSTED_PROXY_COUNT"),
        ({"access_token_minutes": 120}, "ACCESS_TOKEN_MINUTES"),
        ({"ip_hash_key": "short"}, "IP_HASH_KEY"),
        ({"storage_backend": "local"}, "STORAGE_BACKEND"),
        ({"storage_backend": "s3", "s3_bucket": ""}, "S3_BUCKET"),
        ({"storage_backend": "s3", "s3_access_key_id": ""}, "S3_ACCESS_KEY_ID"),
        ({"storage_backend": "s3", "s3_secret_access_key": ""}, "S3_SECRET_ACCESS_KEY"),
        ({"storage_backend": "s3", "s3_secret_access_key": "changeme"}, "S3_SECRET_ACCESS_KEY"),
        ({"storage_backend": "s3", "s3_region": ""}, "S3_REGION"),
        ({"trusted_proxy_count": 2}, "TRUSTED_PROXY_COUNT"),
        ({"cookie_samesite": "none"}, "COOKIE_SAMESITE"),
    ],
)
def test_each_production_problem_is_reported_alone(override, needle):
    problems = validate_production_settings(dict(SAFE, **override))
    assert any(needle in problem for problem in problems), problems


def test_every_problem_at_once_is_reported():
    problems = validate_production_settings(
        {
            "app_env": "production",
            "jwt_secret": "short",
            "cookie_secure": False,
            "cors_origins": "*",
            "enable_docs": True,
            "email_backend": "console",
            "trusted_proxy_count": 0,
            "access_token_minutes": 120,
            "ip_hash_key": "",
            "storage_backend": "local",
        }
    )
    assert len(problems) >= 9


def test_no_secret_value_is_ever_echoed():
    problems = validate_production_settings(dict(SAFE, jwt_secret="short-secret-value"))
    assert all("short-secret-value" not in problem for problem in problems)
