"""Verification-code encryption.

Employee verification codes are encrypted at rest with Fernet (symmetric).
Codes must be viewable again by the admin (to read one out to an employee),
so hashing is not an option here; encryption keeps the plaintext out of the
database while still allowing retrieval. The key is derived from the configured
secret so it works out of the box in development.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


def _fernet() -> Fernet:
    secret = get_settings().verification_code_key or get_settings().secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_code(code: str) -> str:
    return _fernet().encrypt(code.encode()).decode()


def decrypt_code(blob: str) -> str:
    try:
        return _fernet().decrypt(blob.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Stored code cannot be decrypted with the current key.") from exc
