"""Pure serialization, redaction, and validation helpers for audit logs."""

import datetime
import json
import re
import uuid
from decimal import Decimal
from enum import Enum

ENTITY_TYPES = frozenset(
    {
        "division",
        "department",
        "employee",
        "employee_approver",
        "leave_year",
        "leave_type",
        "leave_assignment",
        "leave_balance",
        "weekend_setting",
        "holiday",
        "leave_request",
        "leave_curtailment",
        "report",
        "email",
    }
)

ACTION_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,40}$")

SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "jwt",
    "api_key",
    "hash",
)
REDACTED = "[REDACTED]"

MAX_BYTES = 20000


class AuditValueError(ValueError):
    pass


def _decimal_text(value: Decimal) -> str:
    text = str(value)
    if "E" in text or "e" in text:
        text = format(value, "f")
    return text


def to_jsonable(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_jsonable(value.value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (set, frozenset)):
        return sorted((to_jsonable(item) for item in value), key=str)
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    raise AuditValueError(
        f"Cannot store a {type(value).__name__} value in the audit log. "
        "Convert it to a plain value first."
    )


def _is_sensitive(key) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _redact(value):
    if isinstance(value, dict):
        return {
            key: (REDACTED if _is_sensitive(key) else _redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value


def redact(data):
    return _redact(data)


def changed_fields(old, new) -> list[str]:
    old = old or {}
    new = new or {}
    return sorted(
        key for key in set(old) | set(new) if old.get(key) != new.get(key)
    )


def limit_size(value, max_bytes: int = MAX_BYTES):
    encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    return {"_truncated": True, "approx_bytes": len(encoded)}


def validate_entry(entity_type: str, action: str) -> None:
    if entity_type not in ENTITY_TYPES:
        raise AuditValueError(
            f"Unknown audit entity_type '{entity_type}'. Allowed: "
            f"{', '.join(sorted(ENTITY_TYPES))}."
        )
    if not ACTION_PATTERN.match(action or ""):
        raise AuditValueError(
            f"Invalid audit action '{action}'. Use SCREAMING_SNAKE_CASE, "
            "3-41 characters, starting with a letter."
        )
