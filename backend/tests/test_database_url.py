"""URL handling for Supabase (D-203) — pure functions, no database."""

import pytest

from app.core.config import _to_asyncpg_url
from app.db.urls import connect_args_for, is_pooled

SESSION_POOLER = "postgresql://postgres:pw@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
DIRECT = "postgresql://postgres:pw@db.abcdefgh.supabase.co:5432/postgres?sslmode=require"
TRANSACTION_POOLER = "postgresql://postgres:pw@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
ASYNC = "postgresql+asyncpg://postgres:pw@db.abcdefgh.supabase.co:5432/postgres"


@pytest.mark.parametrize(
    ("pasted", "expected"),
    [
        ("postgresql://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        ("postgres://u:p@h:5432/db", "postgresql+asyncpg://u:p@h:5432/db"),
        (ASYNC, ASYNC),                                   # already correct: untouched
        ("", ""),                                          # nothing to rewrite
        ("sqlite:///x.db", "sqlite:///x.db"),               # other drivers: untouched
    ],
)
def test_the_scheme_is_normalised_for_asyncpg(pasted, expected):
    assert _to_asyncpg_url(pasted) == expected


def test_sslmode_is_translated_for_asyncpg():
    """`sslmode` is libpq syntax, which asyncpg rejects — so it becomes `ssl`."""
    converted = _to_asyncpg_url(DIRECT)
    assert converted.startswith("postgresql+asyncpg://")
    assert converted.endswith("?ssl=require")
    assert "sslmode" not in converted


def test_sslmode_disable_is_dropped_entirely():
    assert _to_asyncpg_url(
        "postgresql://u:p@h:5432/db?sslmode=disable"
    ).endswith("/db")


def test_other_query_parameters_survive():
    converted = _to_asyncpg_url("postgresql://u:p@h:5432/db?application_name=lms&sslmode=require")
    assert "application_name=lms" in converted and "ssl=require" in converted


def test_a_direct_connection_is_not_pooled():
    assert is_pooled(DIRECT) is False
    assert connect_args_for(DIRECT) == {}


def test_the_session_pooler_is_not_treated_as_transaction_mode():
    """Both live on pooler.supabase.com — only the port means pgbouncer mode."""
    assert is_pooled(SESSION_POOLER) is False
    assert connect_args_for(SESSION_POOLER) == {}


def test_the_setting_can_force_it_off_for_an_unusual_pooler():
    assert connect_args_for(SESSION_POOLER, force=True) == {"statement_cache_size": 0}
    assert connect_args_for(DIRECT, force=True) == {"statement_cache_size": 0}


def test_the_transaction_pooler_disables_prepared_statements():
    assert is_pooled(TRANSACTION_POOLER) is True
    assert connect_args_for(TRANSACTION_POOLER) == {"statement_cache_size": 0}


def test_only_the_transaction_pooler_port_counts():
    assert is_pooled("postgresql://u:p@aws-0-x.pooler.supabase.com:6543/db") is True
    assert is_pooled("postgresql://u:p@aws-0-x.pooler.supabase.com:7777/db") is False


@pytest.mark.parametrize("broken", ["", "not a url", "postgresql://u:p@h:notaport/db"])
def test_a_broken_url_never_crashes(broken):
    assert is_pooled(broken) in (True, False)
    assert isinstance(connect_args_for(broken), dict)
