"""The forced-password-change rules (D-190) — pure functions, no database."""

import pytest

from app.services.password_rules import (
    MUST_CHANGE_ALLOWED_PATHS,
    current_password_required,
    MUST_CHANGE_PASSWORD_HEADER,
    may_use_application,
    requires_password_change,
)


# --- who is forced? -------------------------------------------------------
def test_an_admin_creating_an_account_forces_a_change():
    assert requires_password_change(actor_id=1, target_id=None, password_set=True) is True
    assert requires_password_change(actor_id=1, target_id=2, password_set=True) is True


def test_resetting_your_own_password_does_not_force_a_change():
    assert requires_password_change(actor_id=7, target_id=7, password_set=True) is False


def test_no_password_means_the_flag_is_untouched():
    assert requires_password_change(actor_id=1, target_id=2, password_set=False) is False


@pytest.mark.parametrize("explicit", [True, False])
def test_an_explicit_choice_always_wins(explicit):
    # A demo/service account whose password is handed over another way.
    assert requires_password_change(
        actor_id=1, target_id=2, password_set=True, explicit=explicit
    ) is explicit
    assert requires_password_change(
        actor_id=7, target_id=7, password_set=True, explicit=explicit
    ) is explicit


# --- what is allowed while forced? ---------------------------------------
@pytest.mark.parametrize("path", sorted(MUST_CHANGE_ALLOWED_PATHS))
def test_the_way_out_is_always_open(path):
    assert may_use_application(must_change_password=True, path=path) is True


@pytest.mark.parametrize(
    "path",
    [
        "/leave-requests",
        "/leave-requests/new",
        "/leave-balances/me",
        "/employees",
        "/divisions",
        "/reports/balances",
        "/reports/balances/export",
        "/admin/audit-log",
        "/approvals/inbox",
        "/weekends/global",
        "/holidays",
        "/auth/other",
    ],
)
def test_everything_else_is_blocked_while_forced(path):
    assert may_use_application(must_change_password=True, path=path) is False


@pytest.mark.parametrize(
    "path", ["/leave-requests", "/employees", "/reports/balances", "/admin/audit-log"]
)
def test_nothing_is_blocked_when_the_flag_is_clear(path):
    assert may_use_application(must_change_password=False, path=path) is True


def test_the_allowed_set_is_exactly_the_auth_escape_hatches():
    assert MUST_CHANGE_ALLOWED_PATHS == {
        "/auth/me",
        "/auth/change-password",
        "/auth/logout",
        "/auth/logout-all",
        "/auth/refresh",
    }
    assert MUST_CHANGE_PASSWORD_HEADER == "X-Password-Change-Required"


# --- the old password: only for a normal change (D-198) --------------------
def test_the_old_password_is_required_for_a_normal_change():
    assert current_password_required(must_change_password=False) is True


def test_the_forced_first_change_does_not_need_the_old_password():
    assert current_password_required(must_change_password=True) is False


def test_verify_django_pbkdf2_compatibility():
    import base64
    import hashlib
    from app.core.security import verify_password

    # Sample standard Django PBKDF2 hash
    pwd = "secret-password-123"
    salt = "somesalt123"
    iters = 260000
    digest = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt.encode("utf-8"), iters)
    b64_hash = base64.b64encode(digest).decode("ascii").strip()
    django_hash = f"pbkdf2_sha256${iters}${salt}${b64_hash}"

    assert verify_password(pwd, django_hash) is True
    assert verify_password("wrong-password", django_hash) is False
    assert verify_password("", django_hash) is False
    assert verify_password(pwd, "pbkdf2_sha256$invalid$hash") is False
