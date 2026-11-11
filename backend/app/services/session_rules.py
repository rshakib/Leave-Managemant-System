"""Pure rules for formatting and filtering active refresh-token sessions."""

import datetime

# Match specific browsers before generic Chromium/Safari fallback tokens.
_BROWSERS = (
    ("edg/", "Edge"),
    ("opr/", "Opera"),
    ("chrome/", "Chrome"),
    ("crios", "Chrome"),
    ("firefox/", "Firefox"),
    ("fxios", "Firefox"),
    ("safari/", "Safari"),
)

# Match iPad before macOS because iPad User-Agents can contain Mac OS X.
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
    """Return a concise browser/OS label for a User-Agent string."""
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
    if revoked_at is not None or replaced_at is not None:
        return False
    if expires_at is None or expires_at <= now:
        return False
    if family_max_days > 0 and family_started_at + datetime.timedelta(days=family_max_days) <= now:
        return False
    return True


def session_sort_key(session: dict) -> tuple:
    stamp = session.get("last_used_at") or session.get("created_at")
    return (stamp, str(session.get("id")))


def sort_sessions(sessions: list[dict]) -> list[dict]:
    return sorted(sessions, key=session_sort_key, reverse=True)
