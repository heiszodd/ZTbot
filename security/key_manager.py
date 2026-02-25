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


def store_private_key(key_name: str, raw_input: str, label: str = "", chain: str = "solana") -> dict:
    from security.key_utils import normalise_for_storage, get_sol_address_from_any, get_eth_address_from_any, detect_key_type

    if not raw_input or not raw_input.strip():
        raise ValueError("Key input is empty. Please send your seed phrase or private key.")
    if is_encrypted(raw_input):
        raise ValueError("Value appears already encrypted. Pass the raw secret.")

    non_wallet_keys = {"poly_api_key", "poly_api_secret", "poly_api_passphrase"}
    is_wallet = key_name not in non_wallet_keys

    address = ""
    format_used = "raw_secret"
    if is_wallet:
        key_type = detect_key_type(raw_input.strip())
        if key_type == "pubkey_only":
            raise ValueError(
                "❌ That looks like a public address or public key.\n\n"
                "I need your PRIVATE key or seed phrase to execute trades on your behalf.\n\n"
                "Public keys can only read data. Private keys are needed to sign transactions."
            )
        normalised = normalise_for_storage(raw_input, chain)
        format_used = detect_key_type(raw_input)
        if chain == "solana":
            address = get_sol_address_from_any(raw_input)
        else:
            address = get_eth_address_from_any(raw_input)
    else:
        normalised = raw_input.strip()

    encrypted = encrypt_secret(normalised)
    import db

    db.save_encrypted_key({"key_name": key_name, "encrypted": encrypted, "label": label or key_name})
    _key_cache.pop(key_name, None)

    log.info("Key stored: %s chain=%s addr=%s", key_name, chain, (address[:10] + "...") if address else "n/a")
    return {"address": address, "format_used": format_used}


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
    """
    Check if a key is stored.
    Returns False on ANY error —
    never crashes a screen render.
    """
    try:
        import db

        result = db.get_encrypted_key(key_name)
        return result is not None
    except Exception:
        return False
