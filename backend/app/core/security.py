import base64
from datetime import datetime, timedelta, timezone
import hashlib
import secrets

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import settings

MIN_PASSWORD_LENGTH = 8

TOKEN_TYPE = "access"

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def _verify_django_pbkdf2(password: str, password_hash: str) -> bool:
    try:
        parts = password_hash.split("$", 3)
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        _, iterations_str, salt, expected_hash = parts
        iterations = int(iterations_str)
        computed_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        computed_hash = base64.b64encode(computed_digest).decode("ascii").strip()
        return secrets.compare_digest(computed_hash, expected_hash)
    except Exception:
        return False


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2_sha256$"):
        return _verify_django_pbkdf2(password, password_hash)
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError, ValueError):
        return False


def create_access_token(subject: int, expires_minutes: int | None = None) -> str:
    minutes = settings.access_token_minutes if expires_minutes is None else expires_minutes
    payload = {
        "sub": str(subject),
        "type": TOKEN_TYPE,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
