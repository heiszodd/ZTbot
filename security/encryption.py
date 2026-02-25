"""
security/encryption.py
AES-256 symmetric encryption for stored keys.
"""

import os
import logging

log = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    global _fernet
    if _fernet:
        return _fernet

    from cryptography.fernet import Fernet

    key = os.getenv("ENCRYPTION_KEY", "")
    if not key:
        log.warning(
            "ENCRYPTION_KEY not set — generating ephemeral key. "
            "Keys will be lost on restart!"
        )
        key = Fernet.generate_key().decode()

    key = key.strip()
    if key and not key.endswith("="):
        key = key + "=" * ((4 - len(key) % 4) % 4)

    try:
        _fernet = Fernet(key.encode())
        return _fernet
    except Exception as e:
        log.error("Fernet init failed: %s", e)
        _fernet = Fernet(Fernet.generate_key())
        return _fernet


def encrypt_secret(plain: str) -> str:
    """Encrypt a string. Returns base64 token."""
    f = _get_fernet()
    return f.encrypt((plain or "").encode()).decode()


def decrypt_secret(token: str) -> str:
    """Decrypt a stored token. Returns plaintext."""
    f = _get_fernet()
    return f.decrypt((token or "").encode()).decode()


def generate_new_key() -> str:
    """Generate a new encryption key."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


def is_encrypted(value: str) -> bool:
    return bool(value and str(value).startswith("gAAAAA"))


def encrypt_if_needed(value: str) -> str:
    if not value:
        return value
    if is_encrypted(value):
        return value
    return encrypt_secret(value)
