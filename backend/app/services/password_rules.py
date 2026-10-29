"""Pure rules for the forced password change (DECISIONS D-190).

An administrator creates an employee and types a password for them, so that
administrator also knows it. This module decides when the employee must choose
their own password at the next sign-in, and which calls stay allowed until they
have done so.
"""

MUST_CHANGE_PASSWORD_HEADER = "X-Password-Change-Required"

# The only endpoints a forced user may call: the three things they need to get
# out of the situation (change the password, see who they are, sign out).
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
    """Should this employee be forced to choose a new password?

    * an explicit value always wins (the admin can opt a demo/service account out)
    * no password is being set -> the flag is left untouched
    * the actor set SOMEBODY ELSE's password -> force a change
    * the actor set their OWN password -> do not (nobody else knows it)
    """
    if explicit is not None:
        return bool(explicit)
    if not password_set:
        return False
    return actor_id != target_id


def current_password_required(*, must_change_password: bool) -> bool:
    """Must the request carry the OLD password?

    Only when somebody changes a password on their own initiative. During the
    forced first change they typed that very password one moment ago to sign in,
    and the administrator is the one who chose it — asking for it again adds
    nothing (D-198).
    """
    return not must_change_password


def may_use_application(*, must_change_password: bool, path: str) -> bool:
    """True when this request may proceed. A forced user is confined to the
    endpoints in MUST_CHANGE_ALLOWED_PATHS."""
    if not must_change_password:
        return True
    return path in MUST_CHANGE_ALLOWED_PATHS
