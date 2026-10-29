"""SAFETY GUARD for the integration tests.

These tests run `alembic upgrade head` (which can DROP things) and then walk the
whole application against a REAL database. Before a single test is collected the
session aborts unless DATABASE_URL is obviously a throw-away local database:

* the host must be localhost, 127.0.0.1 or the docker service name "postgres";
* the database name must end with "_test";
* the host must not look like a hosted database.

Only the RULE that failed is printed — never the URL itself.
"""

import os
from urllib.parse import urlsplit

import pytest


def _database_url() -> str:
    """The URL to inspect: the environment variable first, then the app settings.

    Reading the settings only ADDS a source — it cannot weaken the guard, because
    every rule below still applies to whatever comes back (a hosted host, or a
    database name that does not end in "_test", is still refused). Without this,
    running the tests with `LMS_ENV_FILE=.env.demo` was refused for the wrong
    reason: the variable simply was not exported.
    """
    from_environment = os.environ.get("DATABASE_URL", "")
    if from_environment:
        return from_environment
    try:
        from app.core.config import settings

        return settings.database_url or ""
    except Exception:  # noqa: BLE001 - unreadable settings means "refuse"
        return ""


def _check() -> None:
    url = _database_url()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    database = (parts.path or "").lstrip("/")

    problems = []
    if host not in ("localhost", "127.0.0.1", "postgres"):
        problems.append("the host is not local")
    if not database.endswith("_test"):
        problems.append('the database name does not end with "_test"')
    if "supabase" in host:
        problems.append("the host looks like a hosted database")

    if problems:
        pytest.exit(
            "Integration tests refused to run: " + "; ".join(problems),
            returncode=1,
        )


@pytest.fixture(scope="session", autouse=True)
def _safety_guard():
    """Fires only when a test in this folder is actually about to RUN.

    A fixture is not executed for deselected tests, so `pytest -q` (which
    excludes the marker) never touches the guard or a database.
    """
    _check()
