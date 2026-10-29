"""The session-list rules (D-191) — pure functions, no database."""

import datetime

import pytest

from app.services.session_rules import (
    UNKNOWN_DEVICE,
    is_active_session,
    sort_sessions,
    summarise_user_agent,
)

NOW = datetime.datetime(2026, 10, 26, 12, 0, tzinfo=datetime.timezone.utc)


# --- device names ---------------------------------------------------------
@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Chrome on Windows"),
        ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0 Safari/537.36 Edg/120.0", "Edge on Windows"),
        ("Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0 Safari/537.36 OPR/106.0", "Opera on Windows"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1", "Safari on iPhone"),
        ("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
         "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1", "Safari on iPad"),
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0 Mobile Safari/537.36", "Chrome on Android"),
        ("Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0",
         "Firefox on Linux"),
        ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
         "Chrome/120.0 Mobile Safari/537.36 CriOS/120.0", "Chrome on Android"),
    ],
)
def test_recognisable_devices(user_agent, expected):
    assert summarise_user_agent(user_agent) == expected


@pytest.mark.parametrize("user_agent", [None, "", "   ", "curl/8.4.0", "SomeBot", "x" * 400])
def test_nothing_is_guessed(user_agent):
    assert summarise_user_agent(user_agent) == UNKNOWN_DEVICE


def test_edge_is_not_reported_as_chrome():
    # No OS in either string, so only the browser is named.
    assert summarise_user_agent("Chrome/120 Safari/537.36 Edg/120") == "Edge"
    assert summarise_user_agent("Chrome/120 Safari/537.36") == "Chrome"
    assert summarise_user_agent("Mozilla/5.0 (Windows NT 10.0) Chrome/120 Safari/537.36 Edg/120") == (
        "Edge on Windows"
    )


# --- is it still a live session? -----------------------------------------
def live(**overrides):
    values = dict(
        revoked_at=None,
        replaced_at=None,
        expires_at=NOW + datetime.timedelta(days=7),
        family_started_at=NOW - datetime.timedelta(days=1),
        now=NOW,
        family_max_days=30,
    )
    values.update(overrides)
    return is_active_session(**values)


def test_a_fresh_session_is_live():
    assert live() is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"revoked_at": NOW},                                  # ended / stolen family
        {"replaced_at": NOW},                                 # rotated away
        {"expires_at": NOW},                                  # the token expired
        {"expires_at": NOW - datetime.timedelta(seconds=1)},
        {"family_started_at": NOW - datetime.timedelta(days=31)},   # family too old
    ],
)
def test_a_finished_session_is_not_listed(overrides):
    assert live(**overrides) is False


def test_the_family_limit_of_zero_means_no_limit():
    assert live(family_started_at=NOW - datetime.timedelta(days=900), family_max_days=0) is True


def test_a_session_at_the_family_limit_is_already_gone():
    assert live(family_started_at=NOW - datetime.timedelta(days=30)) is False


# --- ordering -------------------------------------------------------------
def test_the_most_recently_used_session_comes_first():
    sessions = [
        {"id": "a", "created_at": NOW - datetime.timedelta(days=3),
         "last_used_at": NOW - datetime.timedelta(days=3)},
        {"id": "b", "created_at": NOW - datetime.timedelta(days=2),
         "last_used_at": NOW - datetime.timedelta(minutes=5)},
        {"id": "c", "created_at": NOW - datetime.timedelta(days=1), "last_used_at": None},
    ]
    assert [row["id"] for row in sort_sessions(sessions)] == ["b", "c", "a"]


def test_sorting_does_not_change_the_input_list():
    sessions = [{"id": "a", "created_at": NOW, "last_used_at": NOW}]
    sort_sessions(sessions)
    assert len(sessions) == 1
