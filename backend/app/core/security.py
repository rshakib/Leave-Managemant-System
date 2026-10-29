"""Password hashing (argon2) and JWT helpers.

argon2-cffi is used directly rather than passlib, which is unmaintained and
breaks on newer Python versions (DECISIONS D-43).
"""

from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

MIN_PASSWORD_LENGTH = 8

TOKEN_TYPE = "access"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2 hash for the given password."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True if the password matches the stored hash; False otherwise."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError, ValueError):
        return False


def create_access_token(subject: int, expires_minutes: int | None = None) -> str:
    """Build a signed access token.

    The payload carries only the employee id (`sub`), the token type and the
    expiry — no roles or personal data (DECISIONS D-44).
    """
    minutes = settings.access_token_minutes if expires_minutes is None else expires_minutes
    payload = {
        "sub": str(subject),
        "type": TOKEN_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and validate a token. Raises jwt.PyJWTError subclasses."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
