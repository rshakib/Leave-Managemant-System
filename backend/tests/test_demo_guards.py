"""The demo script's safety guards (Task 2b) — no database needed."""

import os
import pathlib
import subprocess
import sys

import pytest

from app.cli.demo_data import (
    DemoError,
    database_name,
    guard_app_env,
    guard_database_name,
    guard_environment,
    guard_not_a_development_database,
    make_password,
    sample_pdf,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]


# --- guard 1: the acknowledgement flag ------------------------------------
def test_the_flag_is_mandatory():
    with pytest.raises(DemoError) as error:
        guard_environment(acknowledged=False)
    assert "i-understand-this-is-a-demo-database" in str(error.value)


# --- guard 2: production --------------------------------------------------
@pytest.mark.parametrize("app_env", ["production", "PRODUCTION", "Production"])
def test_production_is_refused(app_env):
    with pytest.raises(DemoError):
        guard_app_env(app_env)


@pytest.mark.parametrize("app_env", ["development", "test", ""])
def test_a_non_production_environment_is_accepted(app_env):
    guard_app_env(app_env)


# --- guard 3: the environment-file switch is GONE (D-204) ----------------
def test_no_environment_file_is_needed_any_more():
    """The project uses one configured database; the data check is the guard."""
    guard_environment(acknowledged=True)


# --- guard 4: the database name ------------------------------------------
def test_a_name_must_end_with_demo_test():
    with pytest.raises(DemoError) as error:
        guard_database_name("postgres", allow_remote=False)
    assert "_demo_test" in str(error.value)
    assert "@" not in str(error.value)          # never a URL
    assert "postgresql://" not in str(error.value)


def test_the_demo_test_suffix_is_accepted():
    guard_database_name("lms_demo_test", allow_remote=False)


def test_a_remote_demo_database_needs_the_extra_flag():
    guard_database_name("postgres", allow_remote=True)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@host:5432/demo_case_test", "demo_case_test"),
        ("postgresql://u:p@host:5432/demo_case_test?sslmode=require", "demo_case_test"),
        ("postgresql://u:p@host:5432/demo_case_test/", "demo_case_test"),
        ("", ""),
    ],
)
def test_database_name_never_leaks_credentials(url, expected):
    name = database_name(url)
    assert name == expected
    assert "u" != name and "p" not in name.replace(expected, "")


# --- guard 5: not a development database ---------------------------------
def test_an_empty_database_is_accepted():
    guard_not_a_development_database([])


def test_one_seeded_admin_is_accepted():
    guard_not_a_development_database([{"employee_code": "ADMIN"}])


def test_the_demo_employees_do_not_count():
    guard_not_a_development_database(
        [{"employee_code": "ADMIN"}] + [{"employee_code": f"DEMO-{n:03d}"} for n in range(1, 11)]
    )


def test_a_database_in_use_is_only_accepted_with_the_explicit_flag():
    people = [{"employee_code": "ADMIN"}, {"employee_code": "EMP-002"}]
    guard_not_a_development_database(people, allow_real=True)   # deliberate
    with pytest.raises(DemoError):
        guard_not_a_development_database(people)                # accidental -> refused


def test_two_real_employees_are_refused():
    with pytest.raises(DemoError) as error:
        guard_not_a_development_database(
            [{"employee_code": "ADMIN"}, {"employee_code": "EMP-002"}]
        )
    assert "DEMO-" in str(error.value)


# --- helpers -------------------------------------------------------------
def test_the_sample_pdf_is_a_pdf_and_labelled_as_a_sample():
    blob = sample_pdf("unit test")
    assert blob.startswith(b"%PDF-")
    assert blob.rstrip().endswith(b"%%EOF")
    assert b"SAMPLE DOCUMENT" in blob
    assert len(blob) < 2000


def test_the_shared_password_is_long_random_and_policy_friendly():
    first, second = make_password(), make_password()
    assert first != second
    assert len(first) >= 16
    assert any(character.isdigit() for character in first)
    assert any(character.isupper() for character in first)


# --- the command itself refuses without touching a database --------------
def run_cli(*args, env_file=None, timeout=60):
    env = {**os.environ}
    env.pop("LMS_ENV_FILE", None)
    if env_file:
        env["LMS_ENV_FILE"] = env_file
    return subprocess.run(
        [sys.executable, "-m", "app.cli.demo_data", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True, timeout=timeout,
    )


def test_the_command_refuses_without_the_flag():
    result = run_cli()
    assert result.returncode == 2
    assert "Refused" in result.stdout
    assert "i-understand-this-is-a-demo-database" in result.stdout


def test_the_command_never_prints_a_url_or_a_secret():
    for arguments in ((), ("--i-understand-this-is-a-demo-database",)):
        result = run_cli(*arguments)
        printed = result.stdout + result.stderr
        assert "postgresql://" not in printed
        assert "password=" not in printed
        assert "@" not in printed.replace("Existing admin e-mail", "")


def test_the_help_lists_both_flags():
    result = run_cli("--help")
    assert "--i-understand-this-is-a-demo-database" in result.stdout
    assert "--allow-remote-demo-database" in result.stdout
