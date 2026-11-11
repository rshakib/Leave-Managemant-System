"""Pure rules for forced password changes."""

MUST_CHANGE_PASSWORD_HEADER = "X-Password-Change-Required"

MUST_CHANGE_ALLOWED_PATHS = frozenset(
    {
        "/auth/me",
        "/auth/change-password",
        "/auth/logout",
        "/auth/logout-all",
        "/auth/refresh",
    }
)


def requires_password_change(
    *,
    actor_id: int | None,
    target_id: int | None,
    password_set: bool,
    explicit: bool | None = None,
) -> bool:
    if explicit is not None:
        return bool(explicit)
    if not password_set:
        return False
    return actor_id != target_id


def current_password_required(*, must_change_password: bool) -> bool:
    return not must_change_password


def may_use_application(*, must_change_password: bool, path: str) -> bool:
    if not must_change_password:
        return True
    return path in MUST_CHANGE_ALLOWED_PATHS
