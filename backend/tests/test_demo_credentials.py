"""The demo credentials decision (D-187) — pure functions, no database."""

import pytest

from app.cli.demo_data import (
    CREDENTIALS_HEADER,
    FILE_BROKEN,
    FILE_MISSING,
    FILE_OK,
    CREATE_PASSWORD,
    RESET_PASSWORDS,
    REUSE_PASSWORD,
    STOP,
    decide_credential_action,
    parse_credentials_file,
)

EXPECTED = {
    "DEMO-001": "demo.001@demo.example.com",
    "DEMO-002": "demo.002@demo.example.com",
}
PASSWORD = "Demo-abcdefgh-9Aa"


def good_file(password=PASSWORD, header=CREDENTIALS_HEADER):
    return "\n".join([
        "# DEMO ONLY",
        f"# shared demo password (every demo employee): {password}",
        "",
        header,
        f"DEMO-001,demo.001@demo.example.com,EMPLOYEE,{password}",
        f"DEMO-002,demo.002@demo.example.com,EMPLOYEE/APPROVER,{password}",
        "",
    ])


# --- reading the file -----------------------------------------------------
def test_a_missing_file_is_reported_as_missing():
    assert parse_credentials_file(None, EXPECTED) == (FILE_MISSING, None)


def test_a_complete_file_is_usable_and_yields_the_password():
    state, password = parse_credentials_file(good_file(), EXPECTED)
    assert state == FILE_OK
    assert password == PASSWORD


@pytest.mark.parametrize(
    "text",
    [
        "",                                                   # empty
        "code,email,role,password\n",                         # no shared password
        "# shared demo password:\n" + good_file(),            # empty shared value
        good_file().replace("DEMO-002", "DEMO-009"),          # wrong employee
        good_file().replace("demo.001@demo.example.com", "someone.else@example.com"),
        good_file().replace(f"DEMO-001,demo.001@demo.example.com,EMPLOYEE,{PASSWORD}",
                            "DEMO-001,demo.001@demo.example.com,EMPLOYEE,still-the-old-one"),
        good_file().replace("DEMO-002,demo.002@demo.example.com,EMPLOYEE/APPROVER,"
                            + PASSWORD, "DEMO-002,demo.002@demo.example.com"),
        "garbage without any comma",
    ],
)
def test_a_broken_file_is_reported_as_broken(text):
    state, password = parse_credentials_file(text, EXPECTED)
    assert state == FILE_BROKEN
    assert password is None


def test_a_file_with_the_same_password_everywhere_is_required():
    mixed = good_file().replace("DEMO-001,demo.001@demo.example.com,EMPLOYEE," + PASSWORD,
                               "DEMO-001,demo.001@demo.example.com,EMPLOYEE,another-one")
    assert parse_credentials_file(mixed, EXPECTED)[0] == FILE_BROKEN


def test_the_codes_may_appear_in_any_order():
    text = "\n".join([
        f"# shared demo password (every demo employee): {PASSWORD}",
        CREDENTIALS_HEADER,
        f"DEMO-002,demo.002@demo.example.com,EMPLOYEE,{PASSWORD}",
        f"DEMO-001,demo.001@demo.example.com,EMPLOYEE,{PASSWORD}",
    ])
    assert parse_credentials_file(text, EXPECTED) == (FILE_OK, PASSWORD)


# --- the decision ---------------------------------------------------------
def test_the_first_run_creates_a_password():
    assert decide_credential_action(FILE_MISSING, False, True) == CREATE_PASSWORD
    assert decide_credential_action(FILE_OK, False, True) == CREATE_PASSWORD


def test_an_ok_file_is_reused_for_existing_employees():
    assert decide_credential_action(FILE_OK, True, True) == REUSE_PASSWORD


@pytest.mark.parametrize("state", [FILE_MISSING, FILE_BROKEN])
def test_an_unusable_file_triggers_the_admin_reset(state):
    assert decide_credential_action(state, True, True) == RESET_PASSWORDS


@pytest.mark.parametrize("state", [FILE_MISSING, FILE_BROKEN])
def test_without_a_way_to_reset_the_script_stops(state):
    assert decide_credential_action(state, True, False) == STOP


def test_a_file_is_never_reused_when_it_is_unusable():
    """The bug this fixes: a fresh password while the employees still have the old one."""
    assert decide_credential_action(FILE_BROKEN, True, True) != CREATE_PASSWORD
    assert decide_credential_action(FILE_OK, True, True) != CREATE_PASSWORD
