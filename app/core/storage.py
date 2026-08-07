"""Selfie upload handling: validation (type, size, magic bytes) and persistence.

Uploaded photos live under ``storage/selfies`` (configurable via
``SELFIE_STORAGE_DIR``). Only the stored filename is kept in the database;
the directory is resolved here so tests can redirect it via monkeypatch.
"""

import secrets
import time
from contextlib import suppress
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.services.session_service import SessionError

ALLOWED_SELFIE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}
MAX_SELFIE_BYTES = 2 * 1024 * 1024

DEFAULT_SELFIES_DIR = Path(__file__).resolve().parent.parent.parent / "storage" / "selfies"


def _selfies_dir() -> Path:
    configured = get_settings().selfie_storage_dir
    return Path(configured).resolve() if configured else DEFAULT_SELFIES_DIR


def _magic_matches(data: bytes, content_type: str) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    return False


def save_selfie(upload: UploadFile) -> str:
    """Validate an uploaded selfie and persist it, returning the stored filename.

    Raises ``SessionError`` (code ``invalid_selfie``) when the file is missing,
    an unsupported type, larger than the limit, or not a real image.
    """
    content_type = (upload.content_type or "").lower()
    ext = ALLOWED_SELFIE_TYPES.get(content_type)
    if not ext:
        raise SessionError("Please attach a clear photo of yourself (JPG or PNG).", code="invalid_selfie")
    data = upload.file.read(MAX_SELFIE_BYTES + 1)
    if len(data) > MAX_SELFIE_BYTES:
        raise SessionError("That photo is too large (max 2 MB). Please retake it.", code="invalid_selfie")
    if not _magic_matches(data, content_type):
        raise SessionError("That file doesn't look like a valid photo.", code="invalid_selfie")

    selfies_dir = _selfies_dir()
    selfies_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time() * 1000)}_{secrets.token_hex(8)}{ext}"
    (selfies_dir / filename).write_bytes(data)
    return filename


def delete_selfie(filename: str | None) -> None:
    if not filename:
        return
    with suppress(OSError):
        (_selfies_dir() / filename).unlink(missing_ok=True)


def selfie_path(filename: str) -> Path:
    return _selfies_dir() / filename
