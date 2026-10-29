"""Attachment storage behind a tiny interface (DECISIONS D-11).

`save` / `open_path` / `delete` are all the router needs, so the local-disk
implementation can later be swapped for S3 without touching callers.
"""

import datetime
import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from app.core.config import settings

# Extension -> the "magic bytes" (file signature) the real content must start with.
ALLOWED_SIGNATURES: dict[str, bytes] = {
    "pdf": b"%PDF-",
    "png": b"\x89PNG\r\n\x1a\n",
    "jpg": b"\xff\xd8\xff",
    "jpeg": b"\xff\xd8\xff",
}

CHUNK_BYTES = 64 * 1024


def _media_root() -> Path:
    root = settings.media_path
    root.mkdir(parents=True, exist_ok=True)
    return root


def _too_large() -> HTTPException:
    megabytes = settings.max_upload_bytes // (1024 * 1024)
    return HTTPException(
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        f"The file is larger than {megabytes} MB.",
    )


async def save(upload: UploadFile) -> str:
    """Store the upload and return its path RELATIVE to the media directory.

    The uploaded filename is only used to read the extension — it never becomes
    part of a path (that is how path-traversal bugs happen). The stored name is
    a random UUID.
    """
    suffix = Path(upload.filename or "").suffix.lower().lstrip(".")
    if suffix not in ALLOWED_SIGNATURES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only PDF, PNG, JPG or JPEG files are allowed.",
        )

    # Read in chunks and stop as soon as the limit is passed.
    data = bytearray()
    while True:
        chunk = await upload.read(CHUNK_BYTES)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > settings.max_upload_bytes:
            raise _too_large()

    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty.")

    if not bytes(data).startswith(ALLOWED_SIGNATURES[suffix]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The file content does not match its extension.",
        )

    folder = _media_root() / datetime.date.today().strftime("%Y/%m")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}.{suffix}"
    path.write_bytes(bytes(data))
    return path.relative_to(_media_root()).as_posix()


def resolve(relative: str) -> Path:
    """Turn a stored relative path into an absolute one, refusing escapes."""
    root = _media_root().resolve()
    candidate = (root / relative).resolve()
    if candidate != root and not str(candidate).startswith(str(root) + os.sep):
        # `../..` or an absolute-looking path: never serve outside the media dir.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    return candidate


def open_path(relative: str) -> Path:
    path = resolve(relative)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found.")
    return path


def delete(relative: str) -> None:
    """Best-effort delete (used when the database write fails after saving)."""
    try:
        resolve(relative).unlink(missing_ok=True)
    except HTTPException:
        pass
