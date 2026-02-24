import os
from cryptography.fernet import Fernet, InvalidToken

_fernet = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.getenv("ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY not set in environment variables. "
            "Generate with: "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        )

    try:
        _fernet = Fernet(key.encode())
        return _fernet
    except Exception as e:
        raise RuntimeError(f"ENCRYPTION_KEY is invalid: {e}")


def encrypt_secret(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("Cannot encrypt empty secret")
    f = _get_fernet()
    encrypted = f.encrypt(plaintext.encode())
    return encrypted.decode()


def decrypt_secret(token: str) -> str:
    if not token:
        raise ValueError("Cannot decrypt empty token")
    f = _get_fernet()
    try:
        decrypted = f.decrypt(token.encode())
        return decrypted.decode()
    except InvalidToken:
        raise ValueError(
            "Decryption failed — token is invalid or ENCRYPTION_KEY has changed since encryption"
        )
    except Exception as e:
        raise ValueError(f"Decryption error: {type(e).__name__}")


def encrypt_if_needed(value: str) -> str:
    if not value:
        return value
    if value.startswith("gAAAAA"):
        return value
    return encrypt_secret(value)


def is_encrypted(value: str) -> bool:
    return bool(value and value.startswith("gAAAAA"))


def rotate_encryption(old_key: str, new_key: str, ciphertext: str) -> str:
    old_fernet = Fernet(old_key.encode())
    new_fernet = Fernet(new_key.encode())
    plaintext = old_fernet.decrypt(ciphertext.encode())
    return new_fernet.encrypt(plaintext).decode()
