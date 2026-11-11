"""Pure attachment storage key formatting and validation rules."""

import datetime
import re

ALLOWED_EXTENSIONS = ("pdf", "png", "jpg", "jpeg")

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}

KEY_PATTERN = re.compile(r"^attachments/\d{4}/\d{2}/[0-9a-f]{32}\.(pdf|png|jpg|jpeg)$")
LEGACY_PATTERN = re.compile(r"^[0-9a-f]{32}\.(pdf|png|jpg|jpeg)$")
HEX32 = re.compile(r"^[0-9a-f]{32}$")


class StorageKeyError(ValueError):
    pass


def build_storage_key(now: datetime.datetime, random_hex: str, extension: str) -> str:
    ext = (extension or "").lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise StorageKeyError(
            f"'{extension}' is not an allowed attachment type "
            f"({', '.join(ALLOWED_EXTENSIONS)})."
        )
    if not HEX32.match(random_hex or ""):
        raise StorageKeyError("the random part must be 32 lowercase hex characters.")
    return f"attachments/{now:%Y}/{now:%m}/{random_hex}.{ext}"


def is_valid_storage_key(key) -> bool:
    if not isinstance(key, str) or not key:
        return False
    if key.startswith("/") or key.startswith("."):
        return False
    if ".." in key or "\\" in key or "\x00" in key:
        return False
    if any(ord(character) < 32 for character in key):
        return False
    return bool(KEY_PATTERN.match(key)) or bool(LEGACY_PATTERN.match(key))


def content_type_for_extension(extension: str) -> str:
    ext = (extension or "").lower().lstrip(".")
    if ext not in CONTENT_TYPES:
        raise StorageKeyError(f"'{extension}' has no content type.")
    return CONTENT_TYPES[ext]
