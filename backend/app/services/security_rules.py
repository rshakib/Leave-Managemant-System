"""Pure security rules: tokens, refresh rotation, rate limits, password policy.

No database, no network, no clock: every function takes `now` (or nothing) so it
can be unit-tested directly.
"""

import datetime
import hashlib
import hmac
import secrets
from dataclasses import dataclass

# --- refresh-token outcomes -------------------------------------------------

VALID = "VALID"
EXPIRED = "EXPIRED"
FAMILY_TOO_OLD = "FAMILY_TOO_OLD"
REVOKED = "REVOKED"
REUSED_WITHIN_GRACE = "REUSED_WITHIN_GRACE"
REUSED_THEFT = "REUSED_THEFT"


def hash_token(token: str) -> str:
    """SHA-256 hex of an opaque token — the DB never stores the token itself."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def new_token() -> str:
    """A fresh opaque refresh token (48 random bytes, urlsafe)."""
    return secrets.token_urlsafe(48)


def classify_refresh(row, now, grace_seconds: int, max_family_age_days: int) -> str:
    """Decide what a presented refresh token means.

    `row` carries expires_at, revoked_at, replaced_at and family_started_at.
    A token that was ROTATED (replaced_at set) has been used before: within the
    grace window that is the benign "two tabs refreshed at once" race; after it,
    somebody is replaying a stolen token.
    """
    replaced_at = getattr(row, "replaced_at", None)
    if replaced_at is not None:
        age = (now - replaced_at).total_seconds()
        return REUSED_WITHIN_GRACE if age < grace_seconds else REUSED_THEFT

    if getattr(row, "revoked_at", None) is not None:
        return REVOKED

    if now >= getattr(row, "expires_at"):
        return EXPIRED

    started = getattr(row, "family_started_at", None)
    if started is not None and (now - started).days > max_family_age_days:
        return FAMILY_TOO_OLD

    return VALID


# --- login rate limiting ----------------------------------------------------


@dataclass(frozen=True)
class LoginLimits:
    pair_failures: int = 5
    pair_window_seconds: int = 15 * 60
    ip_failures: int = 30
    ip_window_seconds: int = 15 * 60
    email_failures: int = 20
    email_window_seconds: int = 60 * 60


DEFAULT_LIMITS = LoginLimits()


@dataclass(frozen=True)
class LoginDecision:
    allowed: bool
    retry_after_seconds: int = 0


def _retry_after(failures, limit: int, window_seconds: int, now) -> int:
    """0 when this key is under its limit, otherwise seconds until it clears.

    A block lasts until the OLDEST counted failure drops out of the window.
    """
    cutoff = now - datetime.timedelta(seconds=window_seconds)
    counted = sorted(moment for moment in failures if moment > cutoff)
    if len(counted) < limit:
        return 0
    oldest = counted[0]
    remaining = (oldest + datetime.timedelta(seconds=window_seconds) - now).total_seconds()
    return max(1, int(remaining))


def decide_login(
    now,
    pair_failures,
    ip_failures,
    email_failures,
    limits: LoginLimits = DEFAULT_LIMITS,
) -> LoginDecision:
    """Is this login allowed, given the failures since each key's last success?"""
    waits = [
        _retry_after(pair_failures, limits.pair_failures, limits.pair_window_seconds, now),
        _retry_after(ip_failures, limits.ip_failures, limits.ip_window_seconds, now),
        _retry_after(email_failures, limits.email_failures, limits.email_window_seconds, now),
    ]
    longest = max(waits)
    if longest == 0:
        return LoginDecision(allowed=True, retry_after_seconds=0)
    return LoginDecision(allowed=False, retry_after_seconds=longest)


# --- client IP and hashing --------------------------------------------------


def client_ip(peer_host, forwarded_for_header, trusted_proxy_count: int) -> str:
    """The caller's address, with X-Forwarded-For handled carefully.

    * 0 trusted proxies: the header is IGNORED (any client can send it), so the
      peer address is the truth;
    * n > 0: take the n-th address counted from the RIGHT — the last entries are
      the ones written by our own proxies, so they cannot be forged by the client.
    """
    peer = (peer_host or "").strip()
    if not trusted_proxy_count or trusted_proxy_count < 1:
        return peer

    header = (forwarded_for_header or "").strip()
    if not header:
        return peer

    parts = [part.strip() for part in header.split(",") if part.strip()]
    if len(parts) < trusted_proxy_count:
        return peer
    return parts[-trusted_proxy_count]


def hash_ip(ip: str, key: str) -> str:
    """HMAC-SHA256 hex, so a raw IP address is never stored."""
    return hmac.new(
        (key or "").encode("utf-8"), (ip or "").encode("utf-8"), hashlib.sha256
    ).hexdigest()


# --- password policy --------------------------------------------------------

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128

# The 50 most common passwords (lower-case); checked case-insensitively.
COMMON_PASSWORDS = frozenset(
    {
        "123456", "password", "12345678", "qwerty", "123456789", "12345",
        "1234", "111111", "1234567", "dragon", "123123", "baseball",
        "abc123", "football", "monkey", "letmein", "696969", "shadow",
        "master", "666666", "qwertyuiop", "123321", "mustang", "1234567890",
        "michael", "654321", "pussy", "superman", "1qaz2wsx", "7777777",
        "fuckyou", "121212", "000000", "qazwsx", "123qwe", "killer",
        "trustno1", "jordan", "jennifer", "zxcvbnm", "asdfgh", "hunter",
        "buster", "soccer", "harley", "batman", "andrew", "tigger",
        "sunshine", "iloveyou", "welcome", "admin", "password1", "passw0rd",
    }
)


def check_password_policy(password: str, email: str | None = None) -> list[str]:
    """Readable problems with a NEW password (an empty list means it is fine).

    Existing short passwords keep working at login — this only guards passwords
    being SET (registration, admin creation/reset, change-password).
    """
    text = password or ""
    problems: list[str] = []

    if len(text) < MIN_PASSWORD_LENGTH:
        problems.append(
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters."
        )
    if len(text) > MAX_PASSWORD_LENGTH:
        problems.append(
            f"The password must be at most {MAX_PASSWORD_LENGTH} characters."
        )

    lowered = text.lower()
    if lowered in COMMON_PASSWORDS:
        problems.append("That password is one of the most common ones in the world.")

    if text and len(set(text)) == 1:
        problems.append("The password must not be a single repeated character.")

    if email and "@" in email:
        local_part = email.split("@", 1)[0].lower()
        if len(local_part) >= 4 and local_part in lowered:
            problems.append("The password must not contain your email name.")

    return problems


# --- production configuration guard ----------------------------------------

PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "secret",
        "changeme",
        "change-me",
        "your-secret-key",
        "dev",
        "development",
        "test",
        "please-change-me",
    }
)


def _setting(settings, name, default=None):
    if isinstance(settings, dict):
        return settings.get(name, default)
    return getattr(settings, name, default)


def _cors_origins(settings) -> list[str]:
    raw = _setting(settings, "cors_origins", "") or ""
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [part.strip() for part in str(raw).split(",") if part.strip()]


def validate_production_settings(settings) -> list[str]:
    """Problems that must stop a production start. Empty outside production."""
    if str(_setting(settings, "app_env", "development")).lower() != "production":
        return []

    problems: list[str] = []

    secret = str(_setting(settings, "jwt_secret", "") or "")
    if len(secret) < 32 or secret.lower().strip() in PLACEHOLDER_SECRETS:
        problems.append(
            "JWT_SECRET must be a random value of at least 32 characters (not a "
            "placeholder)."
        )

    if not bool(_setting(settings, "cookie_secure", False)):
        problems.append("COOKIE_SECURE must be true in production (HTTPS only).")

    origins = _cors_origins(settings)
    if not origins:
        problems.append("CORS_ORIGINS must list the real frontend origin(s).")
    for origin in origins:
        lowered = origin.lower()
        if lowered == "*" or "localhost" in lowered or "127.0.0.1" in lowered:
            problems.append(
                f"CORS_ORIGINS must not contain '{origin}' in production."
            )
        elif not lowered.startswith("https://"):
            problems.append(
                f"CORS_ORIGINS entry '{origin}' must use https in production."
            )

    if bool(_setting(settings, "enable_docs", True)):
        problems.append("ENABLE_DOCS must be false in production.")

    if str(_setting(settings, "email_backend", "console")).lower() in ("console", "file"):
        problems.append(
            "EMAIL_BACKEND must be a real backend (smtp) in production."
        )

    # Caddy is the ONE proxy in front of the API. 0 would make every client look
    # like Caddy (one shared rate-limit bucket); more than 1 would trust an entry
    # a client could have written itself.
    if int(_setting(settings, "trusted_proxy_count", 0) or 0) != 1:
        problems.append(
            "TRUSTED_PROXY_COUNT must be exactly 1 in production (Caddy is the only "
            "proxy). 0 makes every client share one address; more than 1 trusts a "
            "value a client could forge."
        )

    samesite = str(_setting(settings, "cookie_samesite", "lax")).lower()
    if samesite not in ("lax", "strict"):
        problems.append("COOKIE_SAMESITE must be 'lax' or 'strict' in production.")

    storage = str(_setting(settings, "storage_backend", "local")).lower()
    if storage == "local":
        problems.append(
            "STORAGE_BACKEND must be 's3' in production: a container's disk is not "
            "permanent, so attachments would disappear on the next deploy."
        )
    elif storage != "s3":
        problems.append("STORAGE_BACKEND must be 'local' or 's3'.")
    else:
        for name, label in (
            ("s3_bucket", "S3_BUCKET"),
            ("s3_access_key_id", "S3_ACCESS_KEY_ID"),
            ("s3_secret_access_key", "S3_SECRET_ACCESS_KEY"),
            ("s3_region", "S3_REGION"),
        ):
            if not str(_setting(settings, name, "") or "").strip():
                problems.append(f"{label} must be set when STORAGE_BACKEND=s3.")
        s3_secret = str(_setting(settings, "s3_secret_access_key", "") or "")
        if s3_secret and s3_secret.lower().strip() in PLACEHOLDER_SECRETS:
            problems.append("S3_SECRET_ACCESS_KEY looks like a placeholder value.")

    ip_key = str(_setting(settings, "ip_hash_key", "") or "")
    if len(ip_key) < 32 or ip_key.lower().strip() in PLACEHOLDER_SECRETS:
        problems.append(
            "IP_HASH_KEY must be a random value of at least 32 characters (it keys "
            "the HMAC that hides client IP addresses)."
        )

    minutes = int(_setting(settings, "access_token_minutes", 15) or 0)
    if minutes > 60:
        problems.append("ACCESS_TOKEN_MINUTES must not exceed 60.")

    return problems
