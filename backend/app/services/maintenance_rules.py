"""Pure data-retention and readiness rules."""

import datetime
from dataclasses import dataclass, field

SENT = "SENT"


@dataclass(frozen=True)
class Readiness:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def retention_cutoffs(now: datetime.datetime, settings) -> dict[str, datetime.datetime]:
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
    unusable_since = replaced_at or revoked_at or expires_at
    if unusable_since is None:
        return False
    return unusable_since < cutoff


def is_prunable_outbox(status, sent_at, cutoff) -> bool:
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
        warnings.append("email")

    return Readiness(ok=not reasons, reasons=reasons, warnings=warnings)
