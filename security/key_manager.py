import logging
import time
from security.encryption import encrypt_secret, decrypt_secret, is_encrypted

log = logging.getLogger(__name__)
_key_cache = {}
_KEY_CACHE_TTL = 300


def _cache_key(key_name: str, value: str) -> None:
    _key_cache[key_name] = {"value": value, "ts": time.time()}


def _get_cached_key(key_name: str) -> str | None:
    entry = _key_cache.get(key_name)
    if not entry:
        return None
    if time.time() - entry["ts"] > _KEY_CACHE_TTL:
        del _key_cache[key_name]
        return None
    return entry["value"]


def _clear_key_cache() -> None:
    _key_cache.clear()
    log.info("Key cache cleared from memory")


def store_private_key(key_name: str, private_key: str, label: str = "") -> None:
    if not private_key:
        raise ValueError("Private key is empty")
    if is_encrypted(private_key):
        raise ValueError("Value appears already encrypted. Pass the raw private key.")

    encrypted = encrypt_secret(private_key)
    import db
    db.save_encrypted_key({"key_name": key_name, "encrypted": encrypted, "label": label})
    log.info(f"Private key stored encrypted: {key_name}")
    _key_cache.pop(key_name, None)


def get_private_key(key_name: str) -> str:
    cached = _get_cached_key(key_name)
    if cached:
        return cached
    import db
    record = db.get_encrypted_key(key_name)
    if not record:
        raise ValueError(f"No key found for: {key_name}")
    plaintext = decrypt_secret(record["encrypted"])
    _cache_key(key_name, plaintext)
    log.info(f"Private key decrypted: {key_name}")
    return plaintext


def delete_private_key(key_name: str) -> None:
    import db
    if not db.is_trading_halted():
        raise RuntimeError("Cannot delete keys while trading is active. Run /stop first.")
    db.delete_encrypted_key(key_name)
    _key_cache.pop(key_name, None)
    log.warning(f"Private key DELETED: {key_name}")


def list_stored_keys() -> list:
    import db
    records = db.list_encrypted_keys()
    return [{"key_name": r["key_name"], "label": r["label"], "stored_at": r["stored_at"]} for r in records]


def key_exists(key_name: str) -> bool:
    import db
    return db.get_encrypted_key(key_name) is not None
