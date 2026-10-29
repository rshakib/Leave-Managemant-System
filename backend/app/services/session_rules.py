"""Pure rules for the "where am I signed in" list (DECISIONS D-191).

One session is one refresh-token FAMILY: every sign-in opens a family, and every
refresh replaces the token inside the same family (D-163). That is why a family,
not a token row, is what the employee sees in the list.
"""

import datetime

# Order matters: Edge and Opera also say "Chrome", and Chrome also says "Safari".
_BROWSERS = (
    ("edg/", "Edge"),
    ("opr/", "Opera"),
    ("chrome/", "Chrome"),
    ("crios", "Chrome"),
    ("firefox/", "Firefox"),
    ("fxios", "Firefox"),
    ("safari/", "Safari"),
)

# Order matters here too: iPad also says "Mac OS X".
_SYSTEMS = (
    ("iphone", "iPhone"),
    ("ipad", "iPad"),
    ("android", "Android"),
    ("crOS".lower(), "ChromeOS"),
    ("windows", "Windows"),
    ("mac os x", "macOS"),
    ("macintosh", "macOS"),
    ("linux", "Linux"),
)

UNKNOWN_DEVICE = "Unknown device"


def summarise_user_agent(user_agent: str | None) -> str:
    """A short, human name for a browser/OS pair.

    The raw string is never shown on its own: it is long, ugly, and easy to make
    look like something else. Anything we cannot recognise becomes
    "Unknown device" rather than a guess.
    """
    value = (user_agent or "").lower()
    if not value.strip():
        return UNKNOWN_DEVICE

    browser = next((name for needle, name in _BROWSERS if needle in value), None)
    system = next((name for needle, name in _SYSTEMS if needle in value), None)
    if browser and system:
        return f"{browser} on {system}"
    if browser:
        return browser
    if system:
        return system
    return UNKNOWN_DEVICE


def is_active_session(
    *,
    revoked_at: datetime.datetime | None,
    replaced_at: datetime.datetime | None,
    expires_at: datetime.datetime,
    family_started_at: datetime.datetime,
    now: datetime.datetime,
    family_max_days: int,
) -> bool:
    """Is this token row a session the employee is still signed in with?

    A row stops being a live session when it was revoked, when it was replaced by
    a rotation, when the token itself expired, or when the whole family is older
    than the family limit (D-163) — the same four ways `classify_refresh` refuses
    a refresh, so the list can never show a session the API would reject.
    """
    if revoked_at is not None or replaced_at is not None:
        return False
    if expires_at is None or expires_at <= now:
        return False
    if family_max_days > 0 and family_started_at + datetime.timedelta(days=family_max_days) <= now:
        return False
    return True


def session_sort_key(session: dict) -> tuple:
    """Newest activity first; a session that never refreshed falls back to its age."""
    stamp = session.get("last_used_at") or session.get("created_at")
    return (stamp, str(session.get("id")))


def sort_sessions(sessions: list[dict]) -> list[dict]:
    return sorted(sessions, key=session_sort_key, reverse=True)
