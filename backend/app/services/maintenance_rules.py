"""Pure data-retention rules (Phase 16D-1).

Nothing here touches a database or a clock: `now` is always passed in.

**What is NEVER pruned** — deliberately, forever:

* `audit_log`            — evidence (D-141, D-147)
* `leave_balance_adjustment` — the money-like ledger (D-155)
* `leave_carry_forward`  — the year-end proof (D-140)
* every business table (employees, requests, balances, holidays, …)

Only three things expire: login telemetry, refresh tokens that can no longer be
used, and emails that were already SENT.
"""

import datetime
from dataclasses import dataclass, field

SENT = "SENT"


@dataclass(frozen=True)
class Readiness:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def retention_cutoffs(now: datetime.datetime, settings) -> dict[str, datetime.datetime]:
    """One cutoff per prunable table: anything OLDER than it may go."""

    def days(name, default):
        value = getattr(settings, name, default)
        return int(value if value is not None else default)

    return {
        "login_attempt": now
        - datetime.timedelta(days=days("retention_login_attempt_days", 30)),
        "refresh_token": now
        - datetime.timedelta(days=days("retention_refresh_token_days", 30)),
        "email_outbox": now
        - datetime.timedelta(days=days("retention_sent_email_days", 90)),
    }


def is_prunable_login_attempt(created_at, cutoff) -> bool:
    return created_at is not None and created_at < cutoff


def is_prunable_refresh_token(expires_at, revoked_at, replaced_at, cutoff) -> bool:
    """A token may go only once it can no longer be used AND it is old enough.

    "Unusable" means expired, revoked (logout / password reset) or already
    replaced by rotation. The newest of those timestamps is the one compared with
    the cutoff, so a token rotated yesterday is kept even if it expired last year.
    """
    unusable_since = replaced_at or revoked_at or expires_at
    if unusable_since is None:
        return False
    return unusable_since < cutoff


def is_prunable_outbox(status, sent_at, cutoff) -> bool:
    """ONLY a SENT email may be pruned.

    PENDING / SENDING / FAILED are the queue itself — deleting them would either
    lose an email or hide a failure an admin still has to retry.
    """
    if status != SENT:
        return False
    return sent_at is not None and sent_at < cutoff


def readiness_state(
    db_ok: bool,
    current_revision,
    head_revision,
    oldest_pending_email_age_seconds,
    stale_after_seconds,
) -> Readiness:
    """Turn the raw checks into a verdict with SHORT, non-sensitive reasons."""
    reasons: list[str] = []
    warnings: list[str] = []

    if not db_ok:
        reasons.append("database")
    elif current_revision != head_revision:
        reasons.append("migrations")

    if (
        oldest_pending_email_age_seconds is not None
        and stale_after_seconds is not None
        and oldest_pending_email_age_seconds > stale_after_seconds
    ):
        # The worker may simply be slow or stopped. That is worth a warning, but
        # the API itself can still serve requests.
        warnings.append("email")

    return Readiness(ok=not reasons, reasons=reasons, warnings=warnings)
